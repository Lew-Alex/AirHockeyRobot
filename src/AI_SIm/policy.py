import torch
from torch import nn
from torch.distributions import Normal


# Obs = puck x/y, puck vx/vy, robot x/y, robot vx/vy, then predicted puck x + arrival time at the home line and the front line
OBSERVATION_SIZE = 12

# Action = robot velocity x, y (between -1 and 1)
ACTION_SIZE = 2


# Actor, picks the action
class Actor(nn.Module):

    def __init__(self, hidden_size=64):
        super().__init__()

        # Layers that pick the preferred action
        self.network = nn.Sequential(
            nn.Linear(OBSERVATION_SIZE, hidden_size),
            nn.Tanh(),
            nn.Linear(hidden_size, hidden_size),
            nn.Tanh(),
            nn.Linear(hidden_size, ACTION_SIZE),
            nn.Tanh(),
        )
        # How random the actions are on each axis (learned)
        self.log_standard_deviation = nn.Parameter(torch.zeros(ACTION_SIZE))

    def forward(self, observation):
        mean = self.network(observation)

        # exp makes sure the std is always positive
        standard_deviation = self.log_standard_deviation.exp().expand_as(mean)

        return mean, standard_deviation

    def distribution(self, observation):
        mean, standard_deviation = self(observation)
        return Normal(mean, standard_deviation)



# Critic, guesses how much reward is coming from a state
class Critic(nn.Module):

    def __init__(self, hidden_size=64):
        super().__init__()

        # Separate network since it judges the state not the action
        self.network = nn.Sequential(
            nn.Linear(OBSERVATION_SIZE, hidden_size),
            nn.Tanh(),
            nn.Linear(hidden_size, hidden_size),
            nn.Tanh(),
            nn.Linear(hidden_size, 1),
        )

    def forward(self, observation):
        return self.network(observation).squeeze(-1)



# Actor + critic together
class ActorCritic(nn.Module):

    def __init__(self, hidden_size=64):
        super().__init__()
        self.actor = Actor(hidden_size)
        self.critic = Critic(hidden_size)

    def act(self, observation, explore=True):
        action_distribution = self.actor.distribution(observation)

        # Sample when training, use the mean when not exploring
        raw_action = action_distribution.sample() if explore else action_distribution.mean

        # Sim only takes actions between -1 and 1
        action = raw_action.clamp(-1.0, 1.0)

        log_probability = action_distribution.log_prob(raw_action).sum(dim=-1)
        value = self.critic(observation)

        return raw_action, action, log_probability, value

    def evaluate(self, observations, raw_actions):
        action_distribution = self.actor.distribution(observations)

        log_probability = action_distribution.log_prob(raw_actions).sum(dim=-1)
        entropy = action_distribution.entropy().sum(dim=-1)
        value = self.critic(observations)

        return log_probability, entropy, value
