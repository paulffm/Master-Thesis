import jax.numpy as jnp
import jax
from typing import Any
import flax
from flax import linen as nn



def get_lambda_t(config, t):
    """Get lambda schedule."""
    if config.get("lambda_t", "const") == "const":
        return jnp.ones(t.shape, dtype=jnp.float32)
    elif config.lambda_t == "grow_linear":
        return 0.5 + t
    elif config.lambda_t == "decay_linear":
        return 1.5 - t
    elif config.lambda_t == "decay_convex":
        return (0.1 + t) ** -0.5
    else:
        raise ValueError("Unknown lambda_t: %s" % config.lambda_t)


def get_logprob_with_logits(cls, xt, t, logits, xt_target=None):
    """Get lobprob with logits."""

    if xt_target is None:
        xt_target = xt
    xt_onehot = jax.nn.one_hot(xt_target, cls.config.vocab_size) # from B, D to B, D, S, should work also with B, H, W, C
    if cls.config.get("logit_type", "direct") == "direct":
        log_prob = nn.log_softmax(logits, axis=-1)
    else:
        qt0 = cls.fwd_model.transition(t)
    if cls.config.logit_type == "reverse_prob":
        p0t = jax.nn.softmax(logits, axis=-1)
        qt0 = jnp.expand_dims(qt0, axis=list(range(1, xt.ndim - 1)))
        prob_all = p0t @ qt0
        log_prob = jnp.log(prob_all + 1e-35)
    elif cls.config.logit_type == "reverse_logscale":
        log_p0t = nn.log_softmax(logits, axis=-1)
        log_qt0 = jnp.where(qt0 <= 1e-35, -1e9, jnp.log(qt0))
        log_qt0 = jnp.expand_dims(log_qt0, axis=list(range(1, xt.ndim)))
        log_p0t = jnp.expand_dims(log_p0t, axis=-1)
        log_prob = jax.nn.logsumexp(log_p0t + log_qt0, axis=-2)
    else:
        raise ValueError("Unknown logit_type: %s" % cls.config.logit_type)
    log_xt = jnp.sum(log_prob * xt_onehot, axis=-1)
    return log_prob, log_xt


@flax.struct.dataclass
class TrainState:
    step: int
    params: Any
    opt_state: Any
    ema_params: Any


def apply_ema(decay, avg, new):
    return jax.tree_map(lambda a, b: decay * a + (1.0 - decay) * b, avg, new)


def copy_pytree(pytree):
    return jax.tree_map(jnp.array, pytree)


def init_state(config, model, model_key):
    # state = init_host_state(make_init_params(config, model.backwd_model, model_key), model.optimizer)
    # laut diesem code: mnist solte discrete_dim als list haben?
    if isinstance(config.discrete_dim, int):
        # input_shape = (config.batch_size, config.discrete_dim)
        input_shape = (1, config.discrete_dim)
    else:
        # input_shape = [config.batch_size] + list(config.discrete_dim)
        input_shape = [1] + list(config.discrete_dim)
    init_kwargs = dict(
        x=jnp.zeros(input_shape, dtype=jnp.int32), t=jnp.zeros((1,), dtype=jnp.float32)
    )

    params = model.backwd_model.net.init({"params": model_key}, **init_kwargs)["params"]
    state = TrainState(
        step=0,
        params=params,
        opt_state=model.optimizer.init(params),
        ema_params=copy_pytree(params),
    )

    return jax.device_get(state)
