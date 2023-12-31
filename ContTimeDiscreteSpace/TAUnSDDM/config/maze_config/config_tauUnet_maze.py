import ml_collections
import os


def get_config():
    save_directory = "SavedModels/MAZEunet/"

    config = ml_collections.ConfigDict()
    config.experiment_name = "maze"
    config.save_location = save_directory

    config.init_model_path = None

    config.device = "cuda"
    config.distributed = False
    config.num_gpus = 0

    config.loss = loss = ml_collections.ConfigDict()
    loss.name = "CTElbo"
    loss.eps_ratio = 1e-9
    loss.nll_weight = 0.001
    loss.min_time = 0.001
    loss.one_forward_pass = True

    config.training = training = ml_collections.ConfigDict()
    training.train_step_name = "Standard"
    training.n_iters = 500000  # 2000 #2000000
    training.clip_grad = True
    training.grad_norm = 1
    training.warmup = 0  # 5000
    training.max_t = 1

    config.data = data = ml_collections.ConfigDict()
    data.name = "Maze3S"
    data.train = True
    data.download = True
    data.S = 3
    data.batch_size = 64  # use 128 if you have enough memory or use distributed
    data.shuffle = True
    data.image_size = 15
    data.shape = [1, data.image_size, data.image_size]
    data.use_augm = False
    data.crop_wall = False
    data.limit = 1
    data.random_transform = True

    config.model = model = ml_collections.ConfigDict()
    model.name = "UniVarUnetEMA"

    model.ema_decay = 0.9999  # 0.9999
    model.padding = True
    model.ch = 64 # data.image_size + 1 if model.padding else data.image_size  # 128
    model.num_res_blocks = 3
    model.ch_mult = [1, 2, 2]  # [1, 2, 2, 2]
    model.input_channels = 1  # 3
    model.scale_count_to_put_attn = 1
    model.data_min_max = [0, 2]
    model.dropout = 0.1
    model.skip_rescale = True
    model.time_embed_dim = model.ch
    model.time_scale_factor = 1000
    model.fix_logistic = False
    model.model_output = 'logits'
    model.num_heads = 8
    model.attn_resolutions = [int(model.ch / 2)]
    model.concat_dim = data.image_size * data.image_size * 1

    model.rate_const = 2.0
    model.t_func = "log_sqr"
    model.Q_sigma = 512.0
    config.optimizer = optimizer = ml_collections.ConfigDict()
    optimizer.name = "Adam"
    optimizer.lr = 2e-4  # 2e-4

    config.saving = saving = ml_collections.ConfigDict()

    saving.checkpoint_freq = 10000
    saving.sample_plot_path = os.path.join(save_directory, "PNGs")

    config.sampler = sampler = ml_collections.ConfigDict()
    sampler.name = "ElboTauL"  # TauLeaping or PCTauLeaping
    sampler.num_steps = 1000
    sampler.min_t = loss.min_time
    sampler.eps_ratio = 1e-9
    sampler.initial_dist = "uniform"
    sampler.num_corrector_steps = 10
    sampler.corrector_step_size_multiplier = float(1.5)
    sampler.corrector_entry_time = float(0.0)
    sampler.is_ordinal = False
    sampler.sample_freq = 2200000

    return config
