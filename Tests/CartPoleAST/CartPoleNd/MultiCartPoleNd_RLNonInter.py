import os
os.environ["CUDA_VISIBLE_DEVICES"]="-1"    #just use CPU

# from garage.tf.algos.trpo import TRPO
from garage.baselines.zero_baseline import ZeroBaseline
from mylab.envs.tfenv import TfEnv
from garage.tf.policies.gaussian_mlp_policy import GaussianMLPPolicy
from garage.tf.policies.gaussian_lstm_policy import GaussianLSTMPolicy
from garage.tf.optimizers.conjugate_gradient_optimizer import ConjugateGradientOptimizer, FiniteDifferenceHvp
from garage.misc import logger

from mylab.rewards.ast_reward import ASTReward
from mylab.envs.ast_env import ASTEnv
from mylab.simulators.policy_simulator import PolicySimulator

from CartPoleNd.cartpole_nd import CartPoleNdEnv

from mylab.algos.trpo import TRPO

import os.path as osp
import argparse
# from example_save_trials import *
import tensorflow as tf
import joblib
import math
import numpy as np

import mcts.BoundedPriorityQueues as BPQ
import csv
# Logger Params
parser = argparse.ArgumentParser()
parser.add_argument('--exp_name', type=str, default="cartpole")
parser.add_argument('--n_trial', type=int, default=5)
parser.add_argument('--trial_start', type=int, default=0)
parser.add_argument('--n_itr', type=int, default=2500)
parser.add_argument('--batch_size', type=int, default=4000)
parser.add_argument('--snapshot_mode', type=str, default="gap")
parser.add_argument('--snapshot_gap', type=int, default=500)
parser.add_argument('--log_dir', type=str, default='./Data/AST/RLNonInter')
parser.add_argument('--args_data', type=str, default=None)
args = parser.parse_args()

top_k = 10
max_path_length = 100
interactive = False

tf.set_random_seed(0)
sess = tf.Session()
sess.__enter__()

# Instantiate the env
env_inner = CartPoleNdEnv(nd=10,use_seed=False)
data = joblib.load("../CartPole/Data/Train/itr_50.pkl")
policy_inner = data['policy']
reward_function = ASTReward()

simulator = PolicySimulator(env=env_inner,policy=policy_inner,max_path_length=max_path_length)
env = TfEnv(ASTEnv(interactive=interactive,
							 simulator=simulator,
							 sample_init_state=False,
							 s_0=[0.0, 0.0, 0.0 * math.pi / 180, 0.0],
							 reward_function=reward_function,
							 ))

# Create policy
policy = GaussianLSTMPolicy(name='lstm_policy',
							env_spec=env.spec,
							hidden_dim=128,
							use_peepholes=True)

with open(osp.join(args.log_dir, 'total_result.csv'), mode='w') as csv_file:
	fieldnames = ['step_count']
	for i in range(top_k):
		fieldnames.append('reward '+str(i))
	writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
	writer.writeheader()

	for trial in range(args.trial_start,args.trial_start+args.n_trial):
		# Create the logger
		log_dir = args.log_dir+'/'+str(trial)

		tabular_log_file = osp.join(log_dir, 'process.csv')
		text_log_file = osp.join(log_dir, 'text.txt')
		params_log_file = osp.join(log_dir, 'args.txt')

		logger.set_snapshot_dir(log_dir)
		logger.set_snapshot_mode(args.snapshot_mode)
		logger.set_snapshot_gap(args.snapshot_gap)
		logger.log_parameters_lite(params_log_file, args)
		if trial > args.trial_start:
			old_log_dir = args.log_dir+'/'+str(trial-1)
			logger.pop_prefix()
			logger.remove_text_output(osp.join(old_log_dir, 'text.txt'))
			logger.remove_tabular_output(osp.join(old_log_dir, 'process.csv'))
		logger.add_text_output(text_log_file)
		logger.add_tabular_output(tabular_log_file)
		logger.push_prefix("["+args.exp_name+'_trial '+str(trial)+"]")

		np.random.seed(trial)

		params = policy.get_params()
		sess.run(tf.variables_initializer(params))
		baseline = ZeroBaseline(env_spec=env.spec)
		optimizer = ConjugateGradientOptimizer(hvp_approach=FiniteDifferenceHvp(base_eps=1e-5))

		top_paths = BPQ.BoundedPriorityQueue(top_k)
		algo = TRPO(
			env=env,
			policy=policy,
			baseline=baseline,
			batch_size=args.batch_size,
			step_size=0.1,
			n_itr=args.n_itr,
			store_paths=True,
			optimizer= optimizer,
			max_path_length=max_path_length,
			top_paths = top_paths,
			plot=False,
			)

		algo.train(sess=sess, init_var=False)

		row_content = dict()
		row_content['step_count'] = args.n_itr*args.batch_size
		i = 0
		for (r,action_seq) in algo.top_paths:
			row_content['reward '+str(i)] = r
			i += 1
		writer.writerow(row_content)