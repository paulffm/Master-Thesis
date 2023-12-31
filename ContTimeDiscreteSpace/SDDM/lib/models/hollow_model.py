"""Hollow networks."""

from typing import Any
from flax import linen as nn
import jax
import jax.numpy as jnp
from lib.models import backward_model
from lib.networks import networks
from lib.networks.unet import UNet


def bidir_transformer(config, x, temb, readout_dim=None):
    """Bidirectional Transformer procedure."""

    if readout_dim is None:
        readout_dim = config.vocab_size
    input_shape = list(x.shape)[:-1]  # x shape: (B, D, emb_dim) => input_shape B, D

    x = jnp.reshape(x, [x.shape[0], -1, x.shape[-1]])  # B, D, E
    if config.net_arch == "bidir_transformer":
        module = networks.UniDirectionalTransformer
    # elif config.net_arch == "bidir_combiner_transformer":
    #    module = networks.CombinerAxial
    else:
        raise ValueError("Unknown net_arch: %s" % config.net_arch)
    l2r_embed = module(config, "l2r")(x, temb)  # x muss hier 3 dim haben: B, D, S
    r2l_embed = module(config, "r2l")(x, temb)  # # temb: (B, embedding_dim)
    # l2r, r2l shape:  B, (D-1) + 2E, E
    if config.bidir_readout == "concat":
        readout_module = networks.ConcatReadout
    elif config.bidir_readout == "res_concat":
        readout_module = networks.ConcatResidualReadout
    elif config.bidir_readout == "attention":
        readout_module = networks.AttentionReadout
    else:
        raise ValueError("Unknown bidir_readout: %s" % config.bidir_readout)
    logits = readout_module(config, readout_dim=readout_dim)(l2r_embed, r2l_embed, temb)
    logits = jnp.reshape(logits, input_shape + [readout_dim])  # (B, D, S)
    return logits  # fehler bei concat_dim - 1 irgendwo: shape hier muss B, D ,S sein


# TypeError: Cannot concatenate arrays with shapes that differ in dimensions other than the one being concatenated: concatenating along dimension 1 for shapes (1, 1, 512), (64, 783, 512).
class BidirectionalTransformer(nn.Module):
    """Transformer in two directions."""

    config: Any

    @nn.compact
    def __call__(self, x, t):
        config = self.config
        x = nn.Embed(config.vocab_size, config.embed_dim)(x)
        temb = networks.transformer_timestep_embedding(
            t * config.time_scale_factor, config.embed_dim
        )  # temb: (B, embedding_dim)
        return bidir_transformer(config, x, temb)


class EnumerativeTransformer(nn.Module):
    """Enumerative transformer."""

    config: Any

    @nn.compact
    def __call__(self, x, t):
        config = self.config
        temb = networks.transformer_timestep_embedding(
            t * config.time_scale_factor, config.embed_dim
        )
        transformer = networks.MaskedTransformer(config)
        # attention: wenn x shape: B, D, S hiernach: B, D * S
        x_shape = x.shape
        x = jnp.reshape(x, [x.shape[0], -1])

        def masked_logits(pos):
            x_masked = x.at[:, pos].set(config.vocab_size)
            logits = transformer(x_masked, temb, pos)
            logits = jnp.squeeze(logits, axis=1)
            return logits

        prefix_cond = config.get("conditional_dim", 0)
        logits = jax.vmap(masked_logits, out_axes=1)(
            jnp.arange(prefix_cond, x.shape[1])
        )
        if prefix_cond:
            dummy_logits = jnp.zeros(
                [x.shape[0], prefix_cond] + list(logits.shape[2:]), dtype=jnp.float32
            )
            logits = jnp.concatenate([dummy_logits, logits], axis=1)
        logits = jnp.reshape(logits, list(x_shape) + [config.vocab_size])
        return logits


def prefix_conditional_forward(x, t, config, net_fn):
    """Logits prediction with prefix conditioning."""
    x = nn.Embed(config.vocab_size, config.embed_dim)(x)
    temb = networks.transformer_timestep_embedding(
        t * config.time_scale_factor, config.embed_dim
    )
    conditioner, x = jnp.split(x, [config.conditional_dim], axis=1)
    logits = net_fn(x, temb, conditioner)
    dummy_logits = jnp.zeros(
        [x.shape[0], config.conditional_dim] + list(logits.shape[2:]), dtype=jnp.float32
    )
    logits = jnp.concatenate([dummy_logits, logits], axis=1)
    assert logits.shape[1] == config.conditional_dim + x.shape[1]
    return logits


class PrefixConditionalBidirTransformer(nn.Module):
    """Transformer in two directions with prefix conditioning."""

    config: Any

    @nn.compact
    def __call__(self, x, t):
        config = self.config

        def logits_fn(x, temb, conditioner):
            if config.net_arch == "bidir_transformer":
                module = networks.UniDirectionalTransformer
            elif config.net_arch == "bidir_combiner_transformer":
                module = networks.CombinerAxial
            else:
                raise ValueError("Unknown net_arch: %s" % config.net_arch)
            l2r_embed = module(config, "l2r")(x, temb, conditioner)[:, -x.shape[1] :]
            r2l_embed = module(config, "r2l")(x, temb, conditioner)[:, : x.shape[1]]
            if config.bidir_readout == "concat":
                readout_module = networks.ConcatReadout
            elif config.bidir_readout == "res_concat":
                readout_module = networks.ConcatResidualReadout
            elif config.bidir_readout == "attn":
                readout_module = networks.AttentionReadout
            else:
                raise ValueError("Unknown bidir_readout: %s" % config.bidir_readout)
            logits = readout_module(config)(l2r_embed, r2l_embed, temb)
            return logits

        return prefix_conditional_forward(x, t, config, logits_fn)


class HollowModel(backward_model.CondFactorizedBackwardModel):
    """Hollow model for discrete data."""

    def __init__(self, config):
        super(HollowModel, self).__init__(config)
        if "bidir" in config.net_arch and "transformer" in config.net_arch:
            self.net = BidirectionalTransformer(config)
            """
            self.net = UNet(
                shape=config.unet_data_shape,
                num_classes=config.unet_num_classes,
                ch=config.unet_dim,
                out_ch=config.unet_outdim,
                ch_mult=config.unet_dim_mults,
                num_res_blocks=config.unet_resnet_block_groups,
                attn_resolutions=config.unet_attn_resolutions,
                num_heads=config.unet_num_heads,
                dropout=config.unet_dropout,
                model_output=config.unet_model_output,  # 'logits' or 'logistic_pars'
                max_time=config.unet_max_time,
                num_pixel_vals=config.vocab_size,
            )
            """
        elif config.net_arch == "enum_transformer":
            self.net = EnumerativeTransformer(config)
        else:
            raise ValueError("Unknown net arch: %s" % config.net_arch)


class PrefixCondHollowModel(HollowModel):
    """Hollow model for discrete data with prefix conditioning."""

    def __init__(self, config):
        super(PrefixCondHollowModel, self).__init__(config)
        if "bidir" in config.net_arch and "transformer" in config.net_arch:
            self.net = PrefixConditionalBidirTransformer(config)
        elif config.net_arch == "enum_transformer":
            self.net = EnumerativeTransformer(config)
        else:
            raise ValueError("Unknown net arch: %s" % config.net_arch)

    def loss(self, params, rng, x0, xt, t):
        del x0, rng
        ll_all, log_xt = self.get_logprob(params, xt, t)
        ll_all = ll_all[:, self.config.conditional_dim :]
        log_xt = log_xt[:, self.config.conditional_dim :]
        loss = self.calc_loss(xt, t, ll_all, log_xt)
        loss = jnp.sum(loss) / xt.shape[0]
        aux = {"loss": loss}
        return loss, aux
