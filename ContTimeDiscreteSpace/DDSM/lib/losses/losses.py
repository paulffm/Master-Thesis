import torch


def loss_fn(score, perturbed_x_grad, perturbed_x, important_sampling_weights=None):
    perturbed_v = sb._inverse(perturbed_x, prevent_nan=True).detach()
    if important_sampling_weights is not None:
        important_sampling_weights = 1/important_sampling_weights[
                    (...,) + (None,) * (x.ndim - 1)]
    else:
        important_sampling_weights = 1
    loss = torch.mean(
            torch.mean(
                important_sampling_weights
                * s[(None,) * (x.ndim - 1)]
                * perturbed_v * (1 - perturbed_v)
                * (gx_to_gv(
                        score, perturbed_x, create_graph=True, compute_gradlogdet=False
                    ) - gx_to_gv(perturbed_x_grad, perturbed_x, compute_gradlogdet=False)
                  ) ** 2,
                dim=(1))
        )
    return loss