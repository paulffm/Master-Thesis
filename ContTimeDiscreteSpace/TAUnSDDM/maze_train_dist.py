import torch
import lib.utils.bookkeeping as bookkeeping
from tqdm import tqdm
import matplotlib.pyplot as plt
import ssl
import os
ssl._create_default_https_context = ssl._create_unverified_context
import lib.models.models as models
import lib.models.model_utils as model_utils
import lib.datasets.datasets as datasets
from lib.datasets.datasets import BinMaze
import lib.datasets.dataset_utils as dataset_utils
import lib.losses.losses as losses
import lib.losses.losses_utils as losses_utils
import lib.training.training as training
import lib.training.training_utils as training_utils
import lib.optimizers.optimizers as optimizers
import lib.optimizers.optimizers_utils as optimizers_utils
import lib.loggers.loggers as loggers
import lib.loggers.logger_utils as logger_utils
import lib.sampling.sampling as sampling
import lib.sampling.sampling_utils as sampling_utils
from lib.datasets.datasets import get_maze_data
from lib.datasets.maze import maze_gen
import lib.sampling.sampling_utils as sampling_utils
import numpy as np
import torch.distributed as dist
import torch.multiprocessing as mp

def setup(rank, world_size, unique_num):
    os.environ['MASTER_ADDR'] = 'localhost'
    os.environ['MASTER_PORT'] = str(12355 + unique_num)
    dist.init_process_group("nccl", rank=rank, world_size=world_size)
    torch.cuda.set_device(rank)

def cleanup():
    dist.destroy_process_group()

def main(rank, world_size, cfg, unique_num):
    print("Training with config", cfg.experiment_name)
    print(f"Rank: {rank}/{world_size}")


    setup(rank, world_size, unique_num)
    ddp_store = dist.FileStore(f"/tmp/tldr_ddpstore_{unique_num}")


    if rank == 0:
        train_resume = False
        save_location = '/Users/paulheller/PythonRepositories/Master-Thesis/ContTimeDiscreteSpace/TAUnSDDM/SavedModels/MNIST/'
        if not train_resume:
            cfg = get_config()
            bookkeeping.save_config(cfg, cfg.save_location)

        else:
            path = save_location
            date = "2023-10-29"
            config_name = "config_001.yaml"
            config_path = os.path.join(path, date, config_name)
            cfg = bookkeeping.load_config(config_path)
            cfg.save_location = save_location

        
        ddp_store.set("save_location", save_location)
        ddp_store.set("checkpoint_dir", save_location)
        ddp_store.set("config_path", config_path)
    dist.barrier()
    save_location = ddp_store.get("save_location")

    if cfg.device == "cpu":
        device = torch.device("cpu")
    elif cfg.device == "cuda":
        device = torch.device(f"cuda:{rank}")

    model = model_utils.create_model(cfg, device, rank)

    loss = losses_utils.get_loss(cfg)

    training_step = training_utils.get_train_step(cfg)

    optimizer = optimizers_utils.get_optimizer(model.parameters(), cfg)

    sampler = sampling_utils.get_sampler(cfg)

    state = {"model": model, "optimizer": optimizer, "n_iter": 0}

    mapping = {'cuda:0': 'cuda:%d' % rank}
    if train_resume:
        checkpoint_path = "SavedModels/MNIST/"
        model_name = "model_7499_rate001.pt"
        checkpoint_path = os.path.join(path, date, model_name)
        state = bookkeeping.load_state(state, checkpoint_path, mapping)
        cfg.training.n_iters = 9000
        cfg.sampler.sample_freq = 9000
        cfg.saving.checkpoint_freq = 500
        bookkeeping.save_config(cfg, cfg.save_location)

    limit = (cfg.training.n_iters - state['n_iter'] + 2) * cfg.data.batch_size
    train_ds = maze_gen(limit=limit, dim_x=7, dim_y=7, pixelSizeOfTile=2, weightHigh=97,weightLow=97)
    dataset = BinMaze(train_ds, cfg.device)
    dist_sampler = torch.utils.data.distributed.DistributedSampler(dataset,
        shuffle=True)
    dataloader = torch.utils.data.DataLoader(dataset,
        batch_size=cfg.data.batch_size//world_size,
        sampler=dist_sampler)


    print("Info:")
    print("--------------------------------")
    print("State Iter:", state["n_iter"])
    print("--------------------------------")
    print("Name Dataset:", cfg.experiment_name)
    print("Loss Name:", cfg.loss.name)
    print("Loss Type:", cfg.loss.loss_type)
    print("Logit Type:", cfg.logit_type)
    print("Ce_coeff:", cfg.ce_coeff)
    print("--------------------------------")
    print("Model Name:", cfg.model.name)
    print("Number of Parameters: ", sum([p.numel() for p in model.parameters()]))
    print("Net Arch:", cfg.net_arch)
    print("Bidir Readout:", cfg.bidir_readout)
    print("Sampler:", cfg.sampler.name)

    n_samples = 16

    print("cfg.saving.checkpoint_freq", cfg.saving.checkpoint_freq)
    training_loss = []
    exit_flag = False
    while True:
        for minibatch in tqdm(dataloader):
            l = training_step.step(state, minibatch, loss)

            training_loss.append(l.item())
            if rank == 0:
                if (state["n_iter"] + 1) % cfg.saving.checkpoint_freq == 0 or state[
                    "n_iter"
                ] == cfg.training.n_iters - 1:
                    bookkeeping.save_state(state, save_location)
                    print("Model saved in Iteration:", state["n_iter"] + 1)

                if (state["n_iter"] + 1) % cfg.sampler.sample_freq == 0 or state[
                    "n_iter"
                ] == cfg.training.n_iters - 1:
                    state["model"].eval()
                    samples = sampler.sample(state["model"], n_samples, 10)
                    samples = samples.reshape(
                        n_samples, 1, cfg.data.image_size, cfg.data.image_size
                    )

                    state["model"].train()
                    samples = samples * 255
                    fig = plt.figure(figsize=(9, 9))
                    for i in range(n_samples):
                        plt.subplot(4, 4, 1 + i)
                        plt.axis("off")
                        plt.imshow(np.transpose(samples[i, ...], (1, 2, 0)), cmap="gray")

                    saving_plot_path = os.path.join(
                        cfg.saving.sample_plot_path, f"{cfg.loss.name}{state['n_iter']}_{cfg.sampler.name}{cfg.sampler.num_steps}.png"
                    )
                    plt.savefig(saving_plot_path)
                    # plt.show()
                    plt.close()

            state["n_iter"] += 1
            if state["n_iter"] > cfg.training.n_iters - 1:
                exit_flag = True
                break

        if exit_flag:
            break

    saving_train_path = os.path.join(
        cfg.saving.sample_plot_path, f"loss_{cfg.loss.name}{state['n_iter']}.png"
    )
    plt.plot(training_loss)
    plt.title("Training loss")
    plt.savefig(saving_train_path)
    plt.close()
    return save_location


if __name__ == "__main__":

    from config.config_hollow_maze import get_config
    cfg = get_config()
    world_size = cfg.num_gpus
    mp.spawn(main,
        args=(world_size, cfg, 0),
        nprocs=world_size,
        join=True
    )
