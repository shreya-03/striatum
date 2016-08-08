"""LinUCB with Disjoint Linear Models
This module contains a class that implements LinUCB with disjoint linear model, a contextual bandit algorithm
assuming the reward function is a linear function of the context.
"""

import six
import logging
from striatum.bandit.bandit import BaseBandit
import numpy as np

LOGGER = logging.getLogger(__name__)


class LinUCB(BaseBandit):
    """LinUCB with Disjoint Linear Models

    Parameters
    ----------
    actions : {array-like, None}
        Actions (arms) for recommendation
    historystorage: a :py:mod:'striatum.storage.HistoryStorage' object
        The object where we store the histories of contexts and rewards.
    modelstorage: a :py:mod:'straitum.storage.ModelStorage' object
        The object where we store the model parameters.
    alpha: float
        The constant determines the width of the upper confidence bound.
    d: int
        The dimension of the context.

    Attributes
    ----------
    linucb\_ : 'linucb' object instance
        The contextual bandit algorithm instances,

    References
    ----------
    .. [1]  Lihong Li, et al. "A Contextual-Bandit Approach to Personalized News Article Recommendation."
            Proceedings of the 19th International Conference on World Wide Web (WWW), 2010.
    """

    def __init__(self, actions, historystorage, modelstorage, alpha, d=1):
        super(LinUCB, self).__init__(historystorage, modelstorage, actions)
        self.last_reward = None
        self.alpha = alpha
        self.d = d
        self.linucb_ = None

        # Initialize LinUCB Model Parameters
        matrix_a = {}  # dictionary - For any action a in actions, matrix_a[a] = (DaT*Da + I) the ridge reg solution.
        matrix_ainv = {}  # dictionary - The inverse of each matrix_a[a] for any action a in actions.
        b = {}  # dictionary - The cumulative return of action a, given the context xt.
        theta = {}  # dictionary - The coefficient vector of actiona with linear model b = dot(xt, theta)

        for actions_id in self._actions_id:
            matrix_a[actions_id] = np.identity(self.d)
            matrix_ainv[actions_id] = np.identity(self.d)
            b[actions_id] = np.zeros((self.d, 1))
            theta[actions_id] = np.zeros((self.d, 1))

        self._modelstorage.save_model({'matrix_a': matrix_a, 'matrix_ainv': matrix_ainv, 'b': b, 'theta': theta})

    @property
    def linucb(self):
        """The generator implementing the disjoint LINUCB algorithm.
        """
        while True:
            context = yield
            context = np.matrix(context)
            matrix_ainv_tmp = np.array(
                [self._modelstorage.get_model()['matrix_ainv'][action_id] for action_id in self._actions_id])
            theta_tmp = np.array([self._modelstorage.get_model()['theta'][action_id] for action_id in self._actions_id])

            # The recommended action should maximize the Linear UCB.
            estimated_reward = {}
            uncertainty = {}
            score = {}
            for actions_id in self._actions_id:
                estimated_reward[actions_id] = np.dot(context[action_id], theta_tmp[action_id])
                uncertainty[actions_id] = self.alpha * np.sqrt(
                    np.dot(np.dot(context[action_id], matrix_ainv_tmp[action_id]), context[action_id].T))
                score[actions_id] = estimated_reward[actions_id] + uncertainty[actions_id]
            yield estimated_reward, uncertainty, score

        raise StopIteration

    def get_action(self, context, n_action=1):
        """Return the action to perform

        Parameters
        ----------
        context : {array-like, None}
            The context of current state, None if no context available.

        n_action: int
                Number of actions wanted to recommend users.

        Returns
        -------
        history_id : int
            The history id of the action.

        action : list of dictionaries
            In each dictionary, it will contains {rank: Action object, estimated_reward, uncertainty}
        """
        if self.linucb_ is None:
            self.linucb_ = self.linucb
            six.next(self.linucb_)
            estimated_reward, uncertainty, score = self.linucb_.send(context)
        else:
            six.next(self.linucb_)
            estimated_reward, uncertainty, score = self.linucb_.send(context)

        action_recommend = []
        actions_recommend_id = [self._actions_id[i] for i in np.array(score.values()).argsort()[-n_action:][::-1]]

        for action_id in actions_recommend_id:
            action = [action for action in self._actions if action.action_id == 1][0]
            estimated_reward = estimated_reward[action_id]
            uncertainty = uncertainty[action_id]
            score = score[action_id]
            action_recommend.append({action, estimated_reward, uncertainty, score})

        history_id = self._historystorage.add_history(context, action_recommend, reward=None)
        return history_id, action_recommend

    def reward(self, history_id, reward):
        """Reward the previous action with reward.

        Parameters
        ----------
        history_id : int
            The history id of the action to reward.

        reward : dictionary
            The dictionary {action_id, reward}, where reward is a float.
        """

        # Update the model
        matrix_a = self._modelstorage.get_model()['matrix_a']
        matrix_ainv = self._modelstorage.get_model()['matrix_ainv']
        b = self._modelstorage.get_model()['b']
        theta = self._modelstorage.get_model()['theta']

        for action_id, reward in reward.items():
            context = self._historystorage.unrewarded_histories[history_id].context[action_id]
            context = np.matrix(context)
            matrix_a[action_id] += np.dot(context.T, context)
            matrix_ainv[action_id] = np.linalg.solve(matrix_a[action_id], np.identity(self.d))
            b[action_id] += reward * context.T
            theta[action_id] = np.dot(matrix_ainv[action_id], b[action_id])
        self._modelstorage.save_model({'matrix_a': matrix_a, 'matrix_ainv': matrix_ainv, 'b': b, 'theta': theta})

        # Update the history
        self._historystorage.add_reward(history_id, reward)

    def add_action(self, actions):
        """ Add new actions (if needed).

            Parameters
            ----------
            actions : {array-like, None}
                Actions (arms) for recommendation
        """
        actions_id = [actions[i].action_id for i in range(len(actions))]
        self._actions.append(actions)
        self._actions_id.extend(actions_id)

        matrix_a = self._modelstorage.get_model()['matrix_a']
        matrix_ainv = self._modelstorage.get_model()['matrix_ainv']
        b = self._modelstorage.get_model()['b']
        theta = self._modelstorage.get_model()['theta']

        for action_id in actions_id:
            if action_id not in self._actions_id:
                matrix_a[action_id] = np.identity(self.d)
                matrix_ainv[action_id] = np.identity(self.d)
                b[action_id] = np.zeros((self.d, 1))
                theta[action_id] = np.zeros((self.d, 1))

        self._modelstorage.save_model({'matrix_a': matrix_a, 'matrix_ainv': matrix_ainv, 'b': b, 'theta': theta})
