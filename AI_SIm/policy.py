"""Actor and critic networks used by the hand-written PPO trainer."""

from __future__ import annotations

import torch
from torch import nn
from torch.distributions import Normal


# -------------------- Policy Shape --------------------

# [puck x/y, puck vx/vy, robot x/y, robot vx/vy]
OBSERVATION_SIZE = 8

# Normalized robot velocity command: [x, y]
ACTION_SIZE = 2


# -------------------- Actor Network --------------------

class Actor(nn.Module):
    """Maps the observed game state to a distribution of X/Y velocities."""

    def __init__(self, hidden_size: int = 64) -> None:
        super().__init__()

        # Fully-connected layers that choose the preferred action.
        self.network = nn.Sequential(
            nn.Linear(OBSERVATION_SIZE, hidden_size),
            nn.Tanh(),
            nn.Linear(hidden_size, hidden_size),
            nn.Tanh(),
            nn.Linear(hidden_size, ACTION_SIZE),
            nn.Tanh(),
        )
        # PPO learns how much random exploration to use on each axis.
        self.log_standard_deviation = nn.Parameter(torch.zeros(ACTION_SIZE))

    def forward(self, observation: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        """Return the preferred X/Y action and exploration amount."""
        mean = self.network(observation)

        # exp() guarantees a positive standard deviation.
        standard_deviation = self.log_standard_deviation.exp().expand_as(mean)

        return mean, standard_deviation

    def distribution(self, observation: torch.Tensor) -> Normal:
        """Create the normal distribution PPO samples actions from."""
        mean, standard_deviation = self(observation)
        return Normal(mean, standard_deviation)


# -------------------- Critic Network --------------------

class Critic(nn.Module):
    """Estimates the discounted future reward for an observed game state."""

    def __init__(self, hidden_size: int = 64) -> None:
        super().__init__()

        # Separate network because this output judges a state, not an action.
        self.network = nn.Sequential(
            nn.Linear(OBSERVATION_SIZE, hidden_size),
            nn.Tanh(),
            nn.Linear(hidden_size, hidden_size),
            nn.Tanh(),
            nn.Linear(hidden_size, 1),
        )

    def forward(self, observation: torch.Tensor) -> torch.Tensor:
        """Return one value estimate for each observation."""
        return self.network(observation).squeeze(-1)


# -------------------- PPO Interface --------------------

class ActorCritic(nn.Module):
    """Keeps the PPO actor and critic together for one policy call."""

    def __init__(self, hidden_size: int = 64) -> None:
        super().__init__()
        self.actor = Actor(hidden_size)
        self.critic = Critic(hidden_size)

    def act(
        self, observation: torch.Tensor, *, explore: bool = True
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """Choose an action and return the values the PPO buffer must store."""
        action_distribution = self.actor.distribution(observation)

        # Sample for exploration while training. Use mean action when deployed.
        raw_action = action_distribution.sample() if explore else action_distribution.mean

        # Simulation actions are restricted to the normalized range [-1, 1].
        action = raw_action.clamp(-1.0, 1.0)

        log_probability = action_distribution.log_prob(raw_action).sum(dim=-1)
        value = self.critic(observation)

        return action, log_probability, value
