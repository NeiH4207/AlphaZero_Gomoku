import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np
import os
from torch.distributions import Categorical
from AdasOptimizer.adasopt_pytorch import Adas
from torch.optim import Adam, SGD
from collections import deque
from tqdm import tqdm
from src.utils import dotdict, AverageMeter, plot

EPS = 0.001

args = dotdict({
    'lr': 0.001,
    'dropout': 0.5,
    'epochs': 20,
    'batch_size': 64,
    'cuda': torch.cuda.is_available(),
    'num_channels': 64,
    'optimizer': 'adas',
})

# 3x3 convolution
def conv3x3(in_channels, out_channels, stride=1):
    return nn.Conv2d(in_channels, out_channels, kernel_size=3, 
                     stride=stride, padding=1, bias=False)

# Residual block
class ResidualBlock(nn.Module):
    def __init__(self, in_channels, out_channels, stride=1, downsample=None):
        super(ResidualBlock, self).__init__()
        self.conv1 = conv3x3(in_channels, out_channels, stride)
        self.bn1 = nn.BatchNorm2d(out_channels)
        self.relu = nn.ReLU(inplace=True)
        self.conv2 = conv3x3(out_channels, out_channels)
        self.bn2 = nn.BatchNorm2d(out_channels)
        self.downsample = downsample
        
    def forward(self, x):
        residual = x
        out = self.conv1(x)
        out = self.bn1(out)
        out = self.relu(out)
        out = self.conv2(out)
        out = self.bn2(out)
        if self.downsample:
            residual = self.downsample(x)
        out += residual
        out = self.relu(out)
        return out
    
# ResNet
class ResNet(nn.Module):
    def __init__(self, block, layers, num_classes=10):
        super(ResNet, self).__init__()
        self.in_channels = args.num_channels
        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        self.layer1 = self.make_layer(block, args.num_channels, layers[0])
        self.layer2 = self.make_layer(block, args.num_channels, layers[1], 2)
        self.layer3 = self.make_layer(block, args.num_channels, layers[2], 2)
        self.avg_pool = nn.AvgPool2d(2)
        
    def make_layer(self, block, out_channels, blocks, stride=1):
        downsample = None
        if (stride != 1) or (self.in_channels != out_channels):
            downsample = nn.Sequential(
                conv3x3(self.in_channels, out_channels, stride=stride).to(self.device),
                nn.BatchNorm2d(out_channels))
        layers = []
        layers.append(block(self.in_channels, out_channels, stride, downsample))
        self.in_channels = out_channels
        for i in range(1, blocks):
            layers.append(block(out_channels, out_channels))
        return nn.Sequential(*layers)
    
    def forward(self, x):
        out = self.layer1(x)
        out = self.layer2(out)
        out = self.layer3(out)
        out = self.avg_pool(out)
        return out
    
class Policy(nn.Module):
    def __init__(self, env):
        # game params
        self.args = args
        self.board_x, self.board_y = env.get_ub_board_size()
        self.action_size = env.n_actions
        self.n_inputs = env.n_inputs
        self.lr = args.lr
        self.env = env
        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        self._elo = [-1000]

        super(Policy, self).__init__()
        self.conv1 = nn.Conv2d(self.n_inputs, args.num_channels, 3, stride=1, padding=1).to(self.device)
        self.conv2 = nn.Conv2d(args.num_channels, args.num_channels, 3, stride=1, padding=1).to(self.device)
        self.conv3 = nn.Conv2d(args.num_channels, args.num_channels, 3, stride=1).to(self.device)
        self.conv4 = nn.Conv2d(args.num_channels, args.num_channels, 3, stride=1).to(self.device)
        
        self.bn1 = nn.BatchNorm2d(args.num_channels).to(self.device)
        self.bn2 = nn.BatchNorm2d(args.num_channels).to(self.device)
        self.bn3 = nn.BatchNorm2d(args.num_channels).to(self.device)
        self.bn4 = nn.BatchNorm2d(args.num_channels).to(self.device)
        
        self.resnet = ResNet(ResidualBlock, [2, 2, 2]).to(self.device)  
        
        self.last_channel_size = int(args.num_channels) * int(int(int((self.board_x + 1) / 2) + 1) / 2 / 2) \
                            * int(int(int((self.board_y + 1) / 2) + 1) / 2 / 2)
        # self.last_channel_size = args.num_channels * (self.board_x - 4) * (self.board_y - 4)
        self.fc1 = nn.Linear(self.last_channel_size, 1024).to(self.device)
        self.fc_bn1 = nn.BatchNorm1d(1024).to(self.device)

        self.fc2 = nn.Linear(1024, 512).to(self.device)
        self.fc_bn2 = nn.BatchNorm1d(512).to(self.device)

        self.fc3 = nn.Linear(512, self.action_size).to(self.device)

        self.fc4 = nn.Linear(512, 1).to(self.device)
        
        self.entropies = 0
        self.pi_losses = AverageMeter()
        self.v_losses = AverageMeter()
        self.action_probs = [[], []]
        self.state_values = [[], []]
        self.rewards = [[], []]
        self.next_states = [[], []]
        if args.optimizer == 'adas':
            self.optimizer = Adas(self.parameters(), lr=self.lr)
        elif args.optimizer == 'adam':
            self.optimizer = Adam(self.parameters(), lr=self.lr)
        else:
            self.optimizer = SGD(self.parameters(), lr=self.lr)

    def forward(self, s):
        #                                                           s: batch_size x n_inputs x board_x x board_y
        s = s.view(-1, self.n_inputs, self.board_x, self.board_y)    # batch_size x n_inputs x board_x x board_y
        s = F.relu(self.bn1(self.conv1(s)))                          # batch_size x num_channels x board_x x board_y
        s = F.relu(self.bn2(self.conv2(s)))                          # batch_size x num_channels x board_x x board_y
        s = F.relu(self.bn3(self.conv3(s)))                          # batch_size x num_channels x (board_x-2) x (board_y-2)
        s = F.relu(self.bn4(self.conv4(s)))                          # batch_size x num_channels x (board_x-4) x (board_y-4)
        s = F.relu(self.resnet(s))
        # print(s.shape)
        # print(self.last_channel_size)
        s = s.view(-1, self.last_channel_size)
        s = F.dropout(F.relu(self.fc1(s)), p=args.dropout, training=self.training)  # batch_size x 1024
        s = F.dropout(F.relu(self.fc2(s)), p=args.dropout, training=self.training)  # batch_size x 512

        pi = self.fc3(s)                                                                         # batch_size x action_size
        v = self.fc4(s)                                                                          # batch_size x 1

        return F.log_softmax(pi, dim=1), torch.tanh(v)
    
    def step(self, obs):
        """
        Returns policy and value estimates for given observations.
        :param obs: Array of shape [N] containing N observations.
        :return: Policy estimate [N, n_actions] and value estimate [N] for
        the given observations.
        """
        obs = torch.from_numpy(obs).to(self.device)
        pi, v = self.forward(obs)

        return torch.exp(pi).detach().to('cpu').numpy(), v.detach().to('cpu').numpy()

    def predict(self, obs):
        obs = self.env.get_states_for_step(obs)
        probs, _ = self.step(obs)
        return probs
    
    def get_value(self, obs):
        obs = self.env.get_states_for_step(obs)
        _, value = self.step(obs)
        return value
        
    def optimize(self):
        self.optimizer.step()
        
    def reset_grad(self):
        self.optimizer.zero_grad()

    def train_examples(self, examples):
        """
        examples: list of examples, each example is of form (board, pi, v)
        """
        for epoch in range(args.epochs):
            # print('\nEPOCH ::: ' + str(epoch + 1))
            self.train()
            batch_count = int(len(examples) / args.batch_size)
            t = tqdm(range(batch_count), desc='Training Net')
            for _ in t:
                sample_ids = np.random.randint(len(examples), size=args.batch_size)
                boards, pis, vs = list(zip(*[examples[i] for i in sample_ids]))
                boards = self.env.get_states_for_step(boards)
                boards = torch.FloatTensor(boards.astype(np.float64)).to(self.device)
                target_pis = torch.FloatTensor(np.array(pis).astype(np.float64))
                target_vs = torch.FloatTensor(np.array(vs).astype(np.float64))

                # predict
                if self.device == 'cuda':
                    boards, target_pis, target_vs = boards.contiguous().cuda(), target_pis.contiguous().cuda(), target_vs.contiguous().cuda()

                # compute output
                out_pi, out_v = self.forward(boards)
                l_pi = self.loss_pi(target_pis, out_pi)
                l_v = self.loss_v(target_vs, out_v)
                total_loss = l_pi + l_v

                # record loss
                self.pi_losses.update(l_pi.item(), boards.size(0))
                self.v_losses.update(l_v.item(), boards.size(0))
                t.set_postfix(Loss_pi=self.pi_losses, Loss_v=self.v_losses)
                # compute gradient and do Adas step
                self.reset_grad()
                total_loss.backward()
                self.optimize()
               
        # self.pi_losses.plot('PolicyLoss')
        # self.v_losses.plot('ValueLoss')
    
    @property
    def elo(self):
        """
        Returns the total scores consits of title, area and treasure scores
        """
        return self._elo[-1]
    
    def update_elo(self, new_elo):
        self._elo.append(new_elo)
    
    def loss_pi(self, targets, outputs):
        return -torch.sum(targets * outputs) / targets.size()[0]

    def loss_v(self, targets, outputs):
        return torch.sum((targets - outputs.view(-1)) ** 2) / targets.size()[0]

    def save_checkpoint(self, folder='Models', filename='model.pt'):
        filepath = os.path.join(folder, filename)
        if not os.path.exists(folder):
            print("Checkpoint Directory does not exist! Making directory {}".format(folder))
            os.mkdir(folder)
        else:
            print("Checkpoint Directory exists! ")
        torch.save({
            'state_dict': self.state_dict(),
            'elo': self._elo,
            'optimizer_state_dict': self.optimizer.state_dict()
        }, filepath)
        
        
    def load_checkpoint(self, folder='Models', filename='model.pt'):
        # https://github.com/pytorch/examples/blob/master/imagenet/main.py#L98
        filepath = os.path.join(folder, filename) 
        if not os.path.exists(filepath):
            raise ("No model in path {}".format(filepath))
        checkpoint = torch.load(filepath, map_location=self.device)
        self.load_state_dict(checkpoint['state_dict'])
        self.optimizer.load_state_dict(checkpoint['optimizer_state_dict'])
        self._elo = checkpoint['elo']
        # self.load_state_dict(checkpoint)
        print('-- Load model succesfull!')
        
    def load_colab_model(self, _dir):
        
        self.load_state_dict(torch.load(_dir, map_location = self.device))
        
    def save_colab_model(self, _dir):
        torch.save(self.state_dict(), _dir)
