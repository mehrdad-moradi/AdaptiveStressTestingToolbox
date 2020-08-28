# Import the example classes
import fire
# Useful imports
import tensorflow as tf
import os
import pickle
import numpy as np
from garage.envs.normalized_env import normalize
from garage.experiment import run_experiment
from garage.np.baselines.linear_feature_baseline import LinearFeatureBaseline
# Import the necessary garage classes
from garage.tf.algos.ppo import PPO
from garage.tf.envs.base import TfEnv
from garage.tf.experiment import LocalTFRunner
from garage.tf.optimizers.conjugate_gradient_optimizer import ConjugateGradientOptimizer
from garage.tf.optimizers.conjugate_gradient_optimizer import FiniteDifferenceHvp
# from garage.tf.policies.gaussian_lstm_policy import GaussianLSTMPolicy
from ast_toolbox.policies.my_gaussian_lstm import GaussianLSTMPolicy

# Import the AST classes
from ast_toolbox.envs import ASTEnv
from ast_toolbox.rewards import ExampleAVReward
from ast_toolbox.samplers import ASTVectorizedSampler
from ast_toolbox.simulators.example_av_simulator.example_av_ast_simulator import ExampleAVASTSimulator
from ast_toolbox.spaces import ExampleAVSpaces


def runner(
    env_args=None,
    run_experiment_args=None,
    sim_args=None,
    reward_args=None,
    spaces_args=None,
    policy_args=None,
    baseline_args=None,
    algo_args=None,
    runner_args=None,
):

    if env_args is None:
        env_args = {}

    if run_experiment_args is None:
        run_experiment_args = {}

    if sim_args is None:
        sim_args = {}

    if reward_args is None:
        reward_args = {}

    if spaces_args is None:
        spaces_args = {}

    if policy_args is None:
        policy_args = {}

    if baseline_args is None:
        baseline_args = {}

    if algo_args is None:
        algo_args = {}

    if runner_args is None:
        runner_args = {'n_epochs': 1}

    if 'n_parallel' in run_experiment_args:
        n_parallel = run_experiment_args['n_parallel']
    else:
        n_parallel = 1
        run_experiment_args['n_parallel'] = n_parallel

    if 'max_path_length' in sim_args:
        max_path_length = sim_args['max_path_length']
    else:
        max_path_length = 50
        sim_args['max_path_length'] = max_path_length

    if 'batch_size' in runner_args:
        batch_size = runner_args['batch_size']
    else:
        batch_size = max_path_length * n_parallel
        runner_args['batch_size'] = batch_size

    def run_task(snapshot_config, *_):

        config = tf.ConfigProto()
        config.gpu_options.allow_growth = True
        with tf.Session(config=config) as sess:
            with tf.variable_scope('AST', reuse=tf.AUTO_REUSE):

                with LocalTFRunner(
                        snapshot_config=snapshot_config, max_cpus=4, sess=sess) as local_runner:
                    # Instantiate the example classes
                    sim = ExampleAVASTSimulator(**sim_args)
                    reward_function = ExampleAVReward(**reward_args)
                    spaces = ExampleAVSpaces(**spaces_args)

                    # Create the environment
                    if 'id' in env_args:
                        env_args.pop('id')
                    env = TfEnv(normalize(ASTEnv(simulator=sim,
                                                 reward_function=reward_function,
                                                 spaces=spaces,
                                                 **env_args
                                                 )))

                    # Instantiate the garage objects
                    policy = GaussianLSTMPolicy(env_spec=env.spec, **policy_args)

                    baseline = LinearFeatureBaseline(env_spec=env.spec, **baseline_args)

                    optimizer = ConjugateGradientOptimizer
                    optimizer_args = {'hvp_approach': FiniteDifferenceHvp(base_eps=1e-5)}

                    algo = PPO(env_spec=env.spec,
                               policy=policy,
                               baseline=baseline,
                               optimizer=optimizer,
                               optimizer_args=optimizer_args,
                               **algo_args)

                    sampler_cls = ASTVectorizedSampler

                    local_runner.setup(
                        algo=algo,
                        env=env,
                        sampler_cls=sampler_cls,
                        sampler_args={"open_loop": env_args['open_loop'],
                                      "sim": sim,
                                      "reward_function": reward_function,
                                      'n_envs': n_parallel})

                    # Run the experiment
                    local_runner.train(**runner_args)

                    last_iter_filename = os.path.join(run_experiment_args['log_dir'],'itr_' + str(runner_args['n_epochs'] - 1) + '.pkl')
                    with open(last_iter_filename, 'rb') as f:
                        last_iter_data = pickle.load(f)

                    best_rollout_idx = np.argmax(np.array([np.sum(rollout['rewards']) for rollout in last_iter_data['paths']]))
                    best_rollout = last_iter_data['paths'][best_rollout_idx]
                    # env_state = self.expert_trajectory[step_num]['state']
                    # env_reward = self.expert_trajectory[step_num]['reward']
                    # env_action = self.expert_trajectory[step_num]['action']
                    # env_observation = self.expert_trajectory[step_num]['observation']
                    expert_trajectory = []
                    collision_step = 1 + np.amax(np.nonzero(best_rollout['rewards']))
                    if collision_step == best_rollout['rewards'].shape[0]:
                        print('NO COLLISION FOUND IN ANY TRAJECTORY - NOT SAVING EXPERT TRAJECTORY')
                    else:
                        for step_num in range(collision_step+1):
                            expert_trajectory_step = {}
                            expert_trajectory_step['action'] = best_rollout['env_infos']['actions'][step_num,:]
                            expert_trajectory_step['observation'] = best_rollout['observations'][step_num, :]
                            expert_trajectory_step['reward'] = best_rollout['rewards'][step_num]
                            expert_trajectory_step['state'] = best_rollout['env_infos']['state'][step_num, :]

                            expert_trajectory.append(expert_trajectory_step)

                        expert_trajectory_filename =  os.path.join(run_experiment_args['log_dir'],'expert_trajectory.pkl')
                        with open(expert_trajectory_filename, 'wb') as f:
                            pickle.dump(expert_trajectory, f)
                        print('done!')

    run_experiment(
        run_task,
        **run_experiment_args,
    )


if __name__ == '__main__':
    fire.Fire()
