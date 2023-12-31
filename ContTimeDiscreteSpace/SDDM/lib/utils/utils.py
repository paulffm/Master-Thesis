"""Utils."""

import functools
from typing import Any
from absl import logging
import flax
import jax
import jax.numpy as jnp
import numpy as np
import optax


def apply_ema(decay, avg, new):
    return jax.tree_map(lambda a, b: decay * a + (1.0 - decay) * b, avg, new)


def copy_pytree(pytree):
    return jax.tree_map(jnp.array, pytree)


@flax.struct.dataclass
class TrainState:
    step: int
    params: Any
    opt_state: Any
    ema_params: Any


def init_host_state(params, optimizer):
    state = TrainState(
        step=0,
        params=params,
        opt_state=optimizer.init(params),
        ema_params=copy_pytree(params),
    )
    return jax.device_get(state)


def init_state(model, model_key):
    state = init_host_state(
        model.backwd_model.make_init_params(model_key), model.optimizer
    )
    return state


def shard_prng_key(prng_key):
    return jax.random.split(prng_key, num=jax.local_device_count())


# gather data over several devices
@functools.partial(jax.pmap, axis_name="shard")
def all_gather(x):
    return jax.lax.all_gather(x, "shard", tiled=True)


def log1mexp(x):
    # Computes log(1-exp(-|x|))
    # https://cran.r-project.org/web/packages/Rmpfr/vignettes/log1mexp-note.pdf
    x = -jnp.abs(x)
    return jnp.where(x > -0.693, jnp.log(-jnp.expm1(x)), jnp.log1p(-jnp.exp(x)))

def log_min_exp(a, b, epsilon=1.e-6):
  """Computes the log(exp(a) - exp(b)) (b<a) in a numerically stable fashion."""
  y = a + jnp.log1p(-jnp.exp(b - a) + epsilon)
  return y


def binary_hamming_sim(x, y):
    x = jnp.expand_dims(x, axis=1)
    y = jnp.expand_dims(y, axis=0)
    d = jnp.sum(jnp.abs(x - y), axis=-1)
    return x.shape[-1] - d


def binary_exp_hamming_sim(x, y, bd):
    x = jnp.expand_dims(x, axis=1)
    y = jnp.expand_dims(y, axis=0)
    d = jnp.sum(jnp.abs(x - y), axis=-1)
    return jnp.exp(-bd * d)


def binary_mmd(x, y, sim_fn):
    """MMD for binary data."""
    x = x.astype(jnp.float32)
    y = y.astype(jnp.float32)
    kxx = sim_fn(x, x)
    kxx = kxx * (1 - jnp.eye(x.shape[0]))
    kxx = jnp.sum(kxx) / x.shape[0] / (x.shape[0] - 1)

    kyy = sim_fn(y, y)
    kyy = kyy * (1 - jnp.eye(y.shape[0]))
    kyy = jnp.sum(kyy) / y.shape[0] / (y.shape[0] - 1)
    kxy = jnp.sum(sim_fn(x, y))
    kxy = kxy / x.shape[0] / y.shape[0]
    mmd = kxx + kyy - 2 * kxy
    return mmd


def binary_exp_hamming_mmd(x, y, bandwidth=0.1):
    sim_fn = functools.partial(binary_exp_hamming_sim, bd=bandwidth)
    return binary_mmd(x, y, sim_fn)


def binary_hamming_mmd(x, y):
    return binary_mmd(x, y, binary_hamming_sim)
