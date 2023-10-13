import torch
import lib.training.training_utils as training_utils
import numpy as np
import time

@training_utils.register_train_step
class Standard():
    def __init__(self, cfg):
        self.do_ema = 'ema_decay' in cfg.model
        self.clip_grad = cfg.training.clip_grad
        self.grad_norm = cfg.training.grad_norm
        self.warmup = cfg.training.warmup
        self.lr = cfg.optimizer.lr

    def step(self, state, minibatch, loss, writer=None):
        state['optimizer'].zero_grad()
        l = loss.calc_loss(minibatch, state, writer)

        #print("Loss in train", l)
        if l.isnan().any() or l.isinf().any():
            #print("Loss is nan")
            assert False
        l.backward()
        end_back = time.time()
        #print("backwards", end_back - start_back)
        start_step = time.time()
        if self.clip_grad:
            torch.nn.utils.clip_grad_norm_(state['model'].parameters(), self.grad_norm)


        if self.warmup > 0:
            for g in state['optimizer'].param_groups:
                g['lr'] = self.lr * np.minimum(state['n_iter'] / self.warmup, 1.0)


        state['optimizer'].step()

        if self.do_ema:
            state['model'].update_ema()
            
        if writer is not None:
            writer.add_scalar('loss', l.detach(), state['n_iter'])

        return l.detach()