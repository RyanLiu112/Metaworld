from collections import OrderedDict
import numpy as np
from gym.spaces import Dict, Box


from multiworld.envs.env_util import get_asset_full_path
from multiworld.envs.mujoco.sawyer_xyz.world_based.base import TaskBased

from pyquaternion import Quaternion
from multiworld.envs.mujoco.utils.rotation import euler2quat


class SawyerWindowOpen6DOFEnv(TaskBased):

    task_schema = Dict({
        'hand_init_pos': Box(low=np.array([-0.5, 0.40, 0.05]), high=np.array([0.5, 1, 0.5]), dtype=np.float32),
        'obj_init_pos': Box(low=np.array([-0.1, 0.7, 0.15]), high=np.array([0.1, 0.9, 0.16]), dtype=np.float32),
        'obj_init_angle': Box(low=-np.pi/4, high=np.pi/4, shape=(1,), dtype=np.float32),
    })

    default_task = {
        'hand_init_pos': np.array([0.1, 0.785, 0.15], dtype=np.float32),
        'obj_init_pos':np.array([-0.1, 0.785, 0.15], dtype=np.float32),
        'obj_init_angle': np.array([0.3], dtype=np.float32),
    } 

    def __init__(
            self,
            liftThresh=0.02,
            rewMode='orig',
            rotMode='fixed',#'fixed',
            if_render=True,
            *args,
            **kwargs
    ):
        self.quick_init(locals())
        TaskBased.__init__(
            self,
            frame_skip=5,
            action_scale=1./100,
            model_name=self.model_name,
            **kwargs
        )
        self.task = self.default_task

        self.max_path_length = 150
        self.rewMode = rewMode
        self.rotMode = rotMode
        self.if_render = if_render
        self.liftThresh = liftThresh
        if rotMode == 'fixed':
            self.action_space = Box(
                np.array([-1, -1, -1, -1]),
                np.array([1, 1, 1, 1]),
            )
        elif rotMode == 'rotz':
            self.action_rot_scale = 1./50
            self.action_space = Box(
                np.array([-1, -1, -1, -np.pi, -1]),
                np.array([1, 1, 1, np.pi, 1]),
            )
        elif rotMode == 'quat':
            self.action_space = Box(
                np.array([-1, -1, -1, 0, -1, -1, -1, -1]),
                np.array([1, 1, 1, 2*np.pi, 1, 1, 1, 1]),
            )
        else:
            self.action_space = Box(
                np.array([-1, -1, -1, -np.pi/2, -np.pi/2, 0, -1]),
                np.array([1, 1, 1, np.pi/2, np.pi/2, np.pi*2, 1]),
            )

        self.observation_space = Dict({
            'hand': self.task_schema.spaces['hand_init_pos'],
            'obj': self.task_schema.spaces['obj_init_pos'],
        })

        self.reset()

    @property
    def model_name(self):     
        return get_asset_full_path('sawyer_xyz/sawyer_window_horizontal.xml')

    @property
    def task(self):
        return self._task

    @task.setter
    def task(self, t):
        self.validate_task(t)
        self._task = t
        self.obj_init_pos = t['obj_init_pos']
        self.obj_init_angle = t['obj_init_angle']
        self.hand_init_pos = t['hand_init_pos']

        # Derive goal from the task
        self._state_goal = self.goal_from_task(t)

    @staticmethod
    def goal_from_task(task):
        goal = task['obj_init_pos'].copy()
        goal[0] += 0.2 
        return goal

    @property
    def state_desired_goal(self):
        return self._state_goal

    def viewer_setup(self):
        self.viewer.cam.trackbodyid = 0
        self.viewer.cam.lookat[0] = 0.2
        self.viewer.cam.lookat[1] = 0.5
        self.viewer.cam.lookat[2] = 0.6
        self.viewer.cam.distance = 0.4
        self.viewer.cam.elevation = -55
        self.viewer.cam.azimuth = 135
        self.viewer.cam.trackbodyid = -1

    def step(self, action):
        if self.if_render:
            self.render()
        # self.set_xyz_action_rot(action[:7])
        if self.rotMode == 'euler':
            action_ = np.zeros(7)
            action_[:3] = action[:3]
            action_[3:] = euler2quat(action[3:6])
            self.set_xyz_action_rot(action_)
        elif self.rotMode == 'fixed':
            self.set_xyz_action(action[:3])
        elif self.rotMode == 'rotz':
            self.set_xyz_action_rotz(action[:4])
        else:
            self.set_xyz_action_rot(action[:7])
        self.do_simulation([action[-1], -action[-1]])
        # The marker seems to get reset every time you do a simulation
        # self._set_goal_marker(np.array([0., self._state_goal, 0.05]))
        self._set_goal_marker(self._state_goal)
        ob = self._get_obs()
        obs_dict = self._get_obs_dict()
        reward, reachDist, pickrew, pullDist = self.compute_reward(action, obs_dict, mode=self.rewMode)
        self.curr_path_length +=1
        #info = self._get_info()
        if self.curr_path_length == self.max_path_length:
            done = True
        else:
            done = False
        return obs_dict, reward, done, {'reachDist': reachDist, 'goalDist': pullDist, 'epRew' : reward, 'pickRew':pickrew}
   
    def _get_obs(self):
        hand = self.get_endeff_pos()
        objPos =  self.data.get_geom_xpos('handle').copy()
        flat_obs = np.concatenate((hand, objPos))
        return flat_obs

    def _get_obs_dict(self):
        hand = self.get_endeff_pos()
        objPos =  self.data.get_geom_xpos('handle').copy()
        objPos[0] -= 0.01
        flat_obs = np.concatenate((hand, objPos))
        return dict(
            hand=hand,
            obj=objPos,
            state_observation=flat_obs,
            state_desired_goal=self._state_goal,
            state_achieved_goal=objPos,
        )

    def _get_info(self):
        pass
    
    def _set_goal_marker(self, goal):
        """
        This should be use ONLY for visualization. Use self._state_goal for
        logging, learning, etc.
        """
        self.data.site_xpos[self.model.site_name2id('goal')] = (
            goal[:3]
        )

    def _set_objCOM_marker(self):
        """
        This should be use ONLY for visualization. Use self._state_goal for
        logging, learning, etc.
        """
        objPos =  self.data.get_geom_xpos('handle')
        self.data.site_xpos[self.model.site_name2id('objSite')] = (
            objPos
        )
    

    def _set_obj_xyz_quat(self, pos, angle):
        quat = Quaternion(axis=[0,0,1], angle=angle).elements
        qpos = self.data.qpos.flat.copy()
        qvel = self.data.qvel.flat.copy()
        qpos[9:12] = pos.copy()
        qpos[12:16] = quat.copy()
        qvel[9:15] = 0
        self.set_state(qpos, qvel)


    def _set_obj_xyz(self, pos):
        qpos = self.data.qpos.flat.copy()
        qvel = self.data.qvel.flat.copy()
        qpos[9] = pos
        # qvel[9:15] = 0
        self.set_state(qpos, qvel)


    def reset_model(self):
        self._reset_hand()
        self.objHeight = self.data.get_geom_xpos('handle')[2]
        self.heightTarget = self.objHeight + self.liftThresh
        self._set_goal_marker(self._state_goal)
        # self._set_obj_xyz(self.obj_init_pos)
        # self._set_obj_xyz_quat(self.obj_init_pos, self.obj_init_angle)
        wall_pos = self.obj_init_pos.copy() - np.array([-0.1, 0, 0.12])
        window_another_pos = self.obj_init_pos.copy() + np.array([0.2, 0.03, 0])
        self.sim.model.body_pos[self.model.body_name2id('window')] = self.obj_init_pos
        self.sim.model.body_pos[self.model.body_name2id('window_another')] = window_another_pos
        self.sim.model.body_pos[self.model.body_name2id('wall')] = wall_pos
        self.sim.model.site_pos[self.model.site_name2id('goal')] = self._state_goal
        self.curr_path_length = 0
        self.maxPullDist = 0.2
        self.target_reward = 1000*self.maxPullDist + 1000*2
        #Can try changing this
        return self._get_obs_dict()

    def _reset_hand(self):
        for _ in range(10):
            self.data.set_mocap_pos('mocap', self.hand_init_pos)
            self.data.set_mocap_quat('mocap', np.array([1, 0, 1, 0]))
            self.do_simulation([-1,1], self.frame_skip)
            #self.do_simulation(None, self.frame_skip)
        rightFinger, leftFinger = self.get_site_pos('rightEndEffector'), self.get_site_pos('leftEndEffector')
        self.init_fingerCOM  =  (rightFinger + leftFinger)/2
        self.pickCompleted = False

    def get_site_pos(self, siteName):
        _id = self.model.site_names.index(siteName)
        return self.data.site_xpos[_id].copy()

    def compute_rewards(self, actions, obsBatch):
        #Required by HER-TD3
        assert isinstance(obsBatch, dict) == True
        obsList = obsBatch['state_observation']
        rewards = [self.compute_reward(action, obs)[0] for  action, obs in zip(actions, obsList)]
        return np.array(rewards)

    def compute_reward(self, actions, obs, mode='general'):
        if isinstance(obs, dict): 
            obs = obs['state_observation']

        objPos = obs[3:6]

        rightFinger, leftFinger = self.get_site_pos('rightEndEffector'), self.get_site_pos('leftEndEffector')
        fingerCOM  =  (rightFinger + leftFinger)/2

        pullGoal = self._state_goal

        pullDist = np.abs(objPos[0] - pullGoal[0])
        reachDist = np.linalg.norm(objPos - fingerCOM)
        heightTarget = self.heightTarget

        c1 = 1000 ; c2 = 0.01 ; c3 = 0.001
        reachRew = -reachDist
        if reachDist < 0.05:
            # pushRew = -pushDist
            pullRew = 1000*(self.maxPullDist - pullDist) + c1*(np.exp(-(pullDist**2)/c2) + np.exp(-(pullDist**2)/c3))
        else:
            pullRew = 0
        reward = reachRew + pullRew
        return [reward, reachDist, None, pullDist]


if __name__ == '__main__':
    import time
    env = SawyerWindowOpen6DOFEnv()
    for _ in range(1000):
        env.reset()
        # for _ in range(10):
        #     env.data.set_mocap_pos('mocap', np.array([0, 0.8, 0.05]))
        #     env.data.set_mocap_quat('mocap', np.array([1, 0, 1, 0]))
        #     env.do_simulation([-1,1], env.frame_skip)
        #     #self.do_simulation(None, self.frame_skip)
        # env._set_obj_xyz(np.array([-0.2, 0.8, 0.05]))
        for _ in range(10):
            env.data.set_mocap_pos('mocap', np.array([-0.15, 0.7, 0.15]))
            env.data.set_mocap_quat('mocap', np.array([1, 0, 1, 0]))
            env.do_simulation([-1,1], env.frame_skip)
            #self.do_simulation(None, self.frame_skip)
        for _ in range(100):
            env.render()
            # env.step(env.action_space.sample())
            # env.step(np.array([0, -1, 0, 0, 0]))
            # if _ < 30:
            #   env.step(np.array([1, 0, 0, 1]))
            # else:
            #   env.step(np.array([1, 0, 1, 1]))
            env.step(np.array([1, 0, 0, 1]))
            # env.step(np.array([np.random.uniform(low=-1., high=1.), np.random.uniform(low=-1., high=1.), 0.]))
            time.sleep(0.05)
