# The Notices and Disclaimers for Ocean Worlds Autonomy Testbed for Exploration
# Research and Simulation can be found in README.md in the root directory of
# this repository.

import rospy
import math
import constants
import copy
import moveit_commander
from moveit_msgs.msg import PositionConstraint, RobotTrajectory
from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint
from tf.transformations import quaternion_from_euler, euler_from_quaternion
from geometry_msgs.msg import Quaternion
from shape_msgs.msg import SolidPrimitive
from std_msgs.msg import Header
from moveit_msgs.srv import GetPositionFK

from ow_actions.common import Singleton, is_shou_yaw_goal_in_range

class ArmTrajectoryPlanner(metaclass = Singleton):

  def __init__(self):
    # basic moveit interface for arm control
    self._robot = moveit_commander.RobotCommander()
    self._move_arm = moveit_commander.MoveGroupCommander('arm')
    self._move_grinder = moveit_commander.MoveGroupCommander('grinder')
    # NOTE: never used
    # self._move_limbs = moveit_commander.MoveGroupCommander('limbs')

    # enable forward kinematic calculations
    SERVICE_TIMEOUT = 30 # seconds
    rospy.wait_for_service('compute_fk', SERVICE_TIMEOUT)
    self._compute_fk_srv = rospy.ServiceProxy('compute_fk', GetPositionFK)

  # def __del__(self):
  #   # persistent service proxies must be manually closed
  #   self._compute_fk_srv.close()

  def compute_forward_kinematics(self, fk_target_link, robot_state):
    # TODO: may raise ROSSerializationException
    goal_pose_stamped = self._compute_fk_srv(
      Header(0, rospy.Time.now(), "base_link")
      [fk_target_link],
      robot_state
    )
    return goal_pose_stamped.pose_stamped[0].pose

  ## DEPRECATED and logic disabled
  def check_for_stop(self, action_name, server_stop):
    # TODO: Strongly suspect this is unnecessary. Will have it return true and
    #       see if that breaks the stop function
    # if server_stop.get_state():
    #   rospy.loginfo('%s was stopped.', action_name)
    #   return True
    # return False
    return False

  def calculate_joint_state_end_pose_from_plan_arm(plan):
    '''
    calculate the end pose (position and orientation), joint states and robot states
    from the current plan
    inputs:  current plan, robot, arm interface, and moveit forward kinematics object
    outputs: goal_pose, robot state and joint states at end of the plan
    '''
    # get joint states from the end of the plan
    joint_states = plan.joint_trajectory.points[-1].positions
    # construct robot state at the end of the plan
    robot_state = self._robot.get_current_state()
    # adding antenna (0,0) and grinder positions (-0.1) which should not change
    new_value = new_value = (
      0, 0) + joint_states[:5] + (-0.1,) + (joint_states[5],)
    # modify current state of robot to the end state of the previous plan
    robot_state.joint_state.position = new_value
    # TODO: may raise ROSSerializationException
    goal_pose = self.compute_forward_kinematics('l_scoop', robot_state)
    return robot_state, joint_states, goal_pose

  def go_to_XYZ_coordinate(cs, goal_pose, x_start, y_start, z_start, approximate=True):
    """
    :param approximate: use an approximate solution. default True
    :type move_group: class 'moveit_commander.move_group.MoveGroupCommander'
    :type x_start: float
    :type y_start: float
    :type z_start: float
    :type approximate: bool
    """

    self._move_arm.set_start_state(cs)
    goal_pose.position.x = x_start
    goal_pose.position.y = y_start
    goal_pose.position.z = z_start

    goal_pose.orientation.x = goal_pose.orientation.x
    goal_pose.orientation.y = goal_pose.orientation.y
    goal_pose.orientation.z = goal_pose.orientation.z
    goal_pose.orientation.w = goal_pose.orientation.w

    # Ask the planner to generate a plan to the approximate joint values generated
    # by kinematics builtin IK solver. For more insight on this issue refer to:
    # https://github.com/nasa/ow_simulator/pull/60
    if approximate:
      self._move_arm.set_joint_value_target(goal_pose, True)
    else:
      self._move_arm.set_pose_target(goal_pose)

    _, plan, _, _ = self._move_arm.plan()

    if len(plan.joint_trajectory.points) == 0:  # If no plan found, abort
      return False

    return plan

  def go_to_Z_coordinate_dig_circular(cs, goal_pose, z_start, approximate=True):
    """
    :type cs: class 'moveit_msgs/RobotState'
    :type goal_pose: Pose
    :type z_start: float
    :param approximate: use an approximate solution. default True
    """

    self._move_arm.set_start_state(cs)
    goal_pose.position.z = z_start

    goal_pose.orientation.x = goal_pose.orientation.x
    goal_pose.orientation.y = goal_pose.orientation.y
    goal_pose.orientation.z = goal_pose.orientation.z
    goal_pose.orientation.w = goal_pose.orientation.w

    # Ask the planner to generate a plan to the approximate joint values generated
    # by kinematics builtin IK solver. For more insight on this issue refer to:
    # https://github.com/nasa/ow_simulator/pull/60
    if approximate:
      self._move_arm.set_joint_value_target(goal_pose, True)
    else:
      self._move_arm.set_pose_target(goal_pose)

    _, plan, _, _ = self._move_arm.plan()

    if len(plan.joint_trajectory.points) == 0:  # If no plan found, abort
      return False

    return plan

  def move_to_pre_trench_configuration_dig_circ(x_start, y_start):
    """
    :type self._move_arm: class 'moveit_commander.move_group.MoveGroupCommander'
    :type x_start: float
    :type y_start: float
    """
    # Initilize to current position
    joint_goal = self._move_arm.get_current_pose().pose
    robot_state = self._robot.get_current_state()
    self._move_arm.set_start_state(robot_state)

    # Compute shoulder yaw angle to trench
    alpha = math.atan2(y_start-constants.Y_SHOU, x_start-constants.X_SHOU)
    h = math.sqrt(pow(y_start-constants.Y_SHOU, 2) +
            pow(x_start-constants.X_SHOU, 2))
    l = constants.Y_SHOU - constants.HAND_Y_OFFSET
    beta = math.asin(l/h)
    # Move to pre trench position, align shoulder yaw
    joint_goal = self._move_arm.get_current_joint_values()
    joint_goal[constants.J_DIST_PITCH] = 0.0
    joint_goal[constants.J_HAND_YAW] = 0.0
    joint_goal[constants.J_PROX_PITCH] = -math.pi/2
    joint_goal[constants.J_SHOU_PITCH] = math.pi/2
    joint_goal[constants.J_SHOU_YAW] = alpha + beta

    # If out of joint range, abort
    if (is_shou_yaw_goal_in_range(joint_goal) == False):
      return False

    joint_goal[constants.J_SCOOP_YAW] = 0

    self._move_arm.set_joint_value_target(joint_goal)
    _, plan, _, _ = self._move_arm.plan()
    return plan

  def dig_circular(args, server_stop):
    """
    :type self._move_arm: class 'moveit_commander.move_group.MoveGroupCommander'
    :type args: List[bool, float, int, float, float, float]
    """

    circ_traj = None
    circ_traj = RobotTrajectory()

    x_start = args.x_start
    y_start = args.y_start
    depth = args.depth
    parallel = args.parallel
    ground_position = args.ground_position

    if not parallel:

      if check_for_stop("dig_circular", server_stop):
        return False

      plan_a = move_to_pre_trench_configuration_dig_circ(x_start, y_start)
      if not plan_a or len(plan_a.joint_trajectory.points) == 0:  # If no plan found, abort
        return False
      # Once aligned to move goal and offset, place scoop tip at surface target offset

      cs, start_state, end_pose = calculate_joint_state_end_pose_from_plan_arm(plan_a)
      z_start = ground_position + constants.R_PARALLEL_FALSE_A  # - depth
      end_pose.position.x = x_start
      end_pose.position.y = y_start
      end_pose.position.z = z_start

      self._move_arm.set_start_state(cs)
      self._move_arm.set_pose_target(end_pose)

      if check_for_stop("dig_circular", server_stop):
        return False
      _, plan_b, _, _ = self._move_arm.plan()
      if len(plan_b.joint_trajectory.points) == 0:  # If no plan found, abort
        return False
      circ_traj = _cascade_plans(plan_a, plan_b)

      # Rotate J_HAND_YAW to correct postion

      cs, start_state, end_pose = calculate_joint_state_end_pose_from_plan_arm(circ_traj)

      if check_for_stop("dig_circular", server_stop):
        return False

      plan_c = change_joint_value(cs, start_state, constants.J_HAND_YAW,  math.pi/2.2)

      circ_traj = _cascade_plans(circ_traj, plan_c)

      cs, start_state, end_pose = calculate_joint_state_end_pose_from_plan_arm(circ_traj)
      # if not parallel:
      # Once aligned to trench goal, place hand above trench middle point
      z_start = ground_position + constants.R_PARALLEL_FALSE_A  # - depth

      if check_for_stop("dig_circular", server_stop):
        return False

      plan_d = go_to_Z_coordinate_dig_circular(cs, end_pose, z_start)
      circ_traj = _cascade_plans(circ_traj, plan_d)

      # Rotate hand perpendicular to arm direction
      cs, start_state, end_pose = calculate_joint_state_end_pose_from_plan_arm(circ_traj)

      if check_for_stop("dig_circular", server_stop):
        return False

      plan_e = change_joint_value(
        cs, start_state, constants.J_HAND_YAW, -0.29*math.pi)
      circ_traj = _cascade_plans(circ_traj, plan_e)

    else:

      if check_for_stop("dig_circular", server_stop):
        return False

      plan_a = move_to_pre_trench_configuration(x_start, y_start)
      if not plan_a or len(plan_a.joint_trajectory.points) == 0:  # If no plan found, abort
        return False
      # Rotate hand so scoop is in middle point
      cs, start_state, end_pose = calculate_joint_state_end_pose_from_plan_arm(
        plan_a)

      if check_for_stop("dig_circular", server_stop):
        return False

      plan_b = change_joint_value(
        cs, start_state, constants.J_HAND_YAW, 0.0)
      circ_traj = _cascade_plans(plan_a, plan_b)

      # Rotate scoop
      cs, start_state, end_pose = calculate_joint_state_end_pose_from_plan_arm(
        circ_traj)

      if check_for_stop("dig_circular", server_stop):
        return False

      plan_c = change_joint_value(
        cs, start_state, constants.J_SCOOP_YAW, math.pi/2)
      circ_traj = _cascade_plans(circ_traj, plan_c)

      # Rotate dist so scoop is back
      cs, start_state, end_pose = calculate_joint_state_end_pose_from_plan_arm(
        circ_traj)

      if check_for_stop("dig_circular", server_stop):
        return False

      plan_d = change_joint_value(
        cs, start_state, constants.J_DIST_PITCH, -19.0/54.0*math.pi)
      circ_traj = _cascade_plans(circ_traj, plan_d)

      # Once aligned to trench goal, place hand above trench middle point
      cs, start_state, end_pose = calculate_joint_state_end_pose_from_plan_arm(
        circ_traj)
      z_start = ground_position + constants.R_PARALLEL_FALSE_A - depth

      if check_for_stop("dig_circular", server_stop):
        return False

      plan_e = go_to_XYZ_coordinate(
        cs, end_pose, x_start, y_start, z_start)
      circ_traj = _cascade_plans(circ_traj, plan_e)

      # Rotate dist to dig
      cs, start_state, end_pose = calculate_joint_state_end_pose_from_plan_arm(
        circ_traj)
      dist_now = start_state[3]

      if check_for_stop("dig_circular", server_stop):
        return False

      plan_f = change_joint_value(
        cs, start_state, constants.J_DIST_PITCH, dist_now + 2*math.pi/3)
      circ_traj = _cascade_plans(circ_traj, plan_f)

    return circ_traj

  def move_to_pre_trench_configuration(x_start, y_start):
    """
    :type x_start: float
    :type y_start: float
    """

    # Initilize to current position
    joint_goal = self._move_arm.get_current_pose().pose
    robot_state = self._robot.get_current_state()
    self._move_arm.set_start_state(robot_state)

  # Compute shoulder yaw angle to trench
    alpha = math.atan2(y_start-constants.Y_SHOU, x_start-constants.X_SHOU)
    h = math.sqrt(pow(y_start-constants.Y_SHOU, 2) +
            pow(x_start-constants.X_SHOU, 2))
    l = constants.Y_SHOU - constants.HAND_Y_OFFSET
    beta = math.asin(l/h)
    # Move to pre trench position, align shoulder yaw
    joint_goal = self._move_arm.get_current_joint_values()
    joint_goal[constants.J_DIST_PITCH] = 0.0
    joint_goal[constants.J_HAND_YAW] = math.pi/2.2
    joint_goal[constants.J_PROX_PITCH] = -math.pi/2
    joint_goal[constants.J_SHOU_PITCH] = math.pi/2
    joint_goal[constants.J_SHOU_YAW] = alpha + beta

    # If out of joint range, abort
    if (is_shou_yaw_goal_in_range(joint_goal) == False):
      return False

    joint_goal[constants.J_SCOOP_YAW] = 0
    self._move_arm.set_joint_value_target(joint_goal)
    _, plan, _, _ = self._move_arm.plan()
    return plan

  def plan_cartesian_path(move_group, wpose, length, alpha, parallel, z_start, cs):
    """
    :type move_group: class 'moveit_commander.move_group.MoveGroupCommander'
    :type length: float
    :type alpha: float
    :type parallel: bool
    """
    if parallel == False:
      alpha = alpha - math.pi/2
    move_group.set_start_state(cs)
    waypoints = []
    wpose.position.z = z_start
    wpose.position.x += length*math.cos(alpha)
    wpose.position.y += length*math.sin(alpha)
    waypoints.append(copy.deepcopy(wpose))

    (plan, fraction) = move_group.compute_cartesian_path(
      waypoints,   # waypoints to follow
      0.01,        # end effector follow step (meters)
      0.0)         # jump threshold

    return plan, fraction

  def plan_cartesian_path_lin(wpose, length, alpha, z_start, cs):
    """
    :type length: float
    :type alpha: float
    """
    self._move_arm.set_start_state(cs)
    waypoints = []

    wpose.position.x += length*math.cos(alpha)
    wpose.position.y += length*math.sin(alpha)

    waypoints.append(copy.deepcopy(wpose))

    (plan, fraction) = self._move_arm.compute_cartesian_path(
      waypoints,   # waypoints to follow
      0.01,        # end effector follow step (meters)
      0.0)         # jump threshold

    return plan, fraction

  def change_joint_value(cs, start_state, joint_index, target_value):
    """
    :type move_group: class 'moveit_commander.move_group.MoveGroupCommander'
    :type joint_index: int
    :type target_value: float
    """
    self._move_arm.set_start_state(cs)

    joint_goal = self._move_arm.get_current_joint_values()
    for k in range(0, len(start_state)):
      joint_goal[k] = start_state[k]

    joint_goal[joint_index] = target_value
    self._move_arm.set_joint_value_target(joint_goal)
    _, plan, _, _ = self._move_arm.plan()
    return plan

  def go_to_Z_coordinate(cs, goal_pose, x_start, y_start, z_start, approximate=True):
    """
    :param approximate: use an approximate solution. default True
    :type x_start: float
    :type y_start: float
    :type z_start: float
    :type approximate: bool
    """

    self._move_arm.set_start_state(cs)

    goal_pose.position.x = x_start
    goal_pose.position.y = y_start
    goal_pose.position.z = z_start

    # Ask the planner to generate a plan to the approximate joint values generated
    # by kinematics builtin IK solver. For more insight on this issue refer to:
    # https://github.com/nasa/ow_simulator/pull/60
    if approximate:
      self._move_arm.set_joint_value_target(goal_pose, True)
    else:
      self._move_arm.set_pose_target(goal_pose)
    _, plan, _, _ = self._move_arm.plan()
    if len(plan.joint_trajectory.points) == 0:  # If no plan found, abort
      return False
    return plan

  def dig_linear(args, server_stop):
    """
    :type args: List[bool, float, int, float, float, float]
    """
    x_start = args.x_start
    y_start = args.y_start
    depth = args.depth
    length = args.length
    ground_position = args.ground_position

    if check_for_stop("dig_linear", server_stop):
      return False

    plan_a = move_to_pre_trench_configuration(x_start, y_start)
    if not plan_a or len(plan_a.joint_trajectory.points) == 0:  # If no plan found, abort
      return False

    cs, start_state, current_pose = calculate_joint_state_end_pose_from_plan_arm(
      plan_a)
    #################### Rotate hand yaw to dig in#################################
    if check_for_stop("dig_linear", server_stop):
      return False

    plan_b = change_joint_value(cs, start_state, constants.J_HAND_YAW, 0.0)

    # If no plan found, send the previous plan only
    if len(plan_b.joint_trajectory.points) == 0:
      return plan_a

    dig_linear_traj = _cascade_plans(plan_a, plan_b)

    ######################### rotate scoop #######################################

    cs, start_state, current_pose = calculate_joint_state_end_pose_from_plan_arm(
      dig_linear_traj)

    if check_for_stop("dig_linear", server_stop):
      return False

    plan_c = change_joint_value(
      cs, start_state, constants.J_SCOOP_YAW, math.pi/2)

    dig_linear_traj = _cascade_plans(dig_linear_traj, plan_c)

    ######################### rotate dist pith to pre-trenching position###########

    cs, start_state, current_pose = calculate_joint_state_end_pose_from_plan_arm(
      dig_linear_traj)

    if check_for_stop("dig_linear", server_stop):
      return False

    plan_d = change_joint_value(
      cs, start_state, constants.J_DIST_PITCH, -math.pi/2)

    dig_linear_traj = _cascade_plans(dig_linear_traj, plan_d)

    # Once aligned to trench goal,
    # place hand above the desired start point
    alpha = math.atan2(constants.WRIST_SCOOP_PARAL,
               constants.WRIST_SCOOP_PERP)
    distance_from_ground = constants.ROT_RADIUS * \
      (math.cos(alpha) - math.sin(alpha))
    z_start = ground_position + constants.SCOOP_HEIGHT - depth + distance_from_ground

    cs, start_state, goal_pose = calculate_joint_state_end_pose_from_plan_arm(
      dig_linear_traj)

    if check_for_stop("dig_linear", server_stop):
      return False

    plan_e = go_to_Z_coordinate(
      cs, goal_pose, x_start, y_start, z_start)

    dig_linear_traj = _cascade_plans(dig_linear_traj, plan_e)

    # rotate to dig in the ground

    cs, start_state, goal_pose = calculate_joint_state_end_pose_from_plan_arm(
      robot, dig_linear_traj)

    if check_for_stop("dig_linear", server_stop):
      return False

    plan_f = change_joint_value(
      cs, start_state, constants.J_DIST_PITCH, 2.0/9.0*math.pi)

    dig_linear_traj = _cascade_plans(dig_linear_traj, plan_f)

    # determine linear trenching direction (alpha) value obtained from rviz

    cs, start_state, current_pose = calculate_joint_state_end_pose_from_plan_arm(
      dig_linear_traj)

    quaternion = [current_pose.orientation.x, current_pose.orientation.y,
            current_pose.orientation.z, current_pose.orientation.w]
    current_euler = euler_from_quaternion(quaternion)
    alpha = current_euler[2]

    # linear trenching

    cs, start_state, current_pose = calculate_joint_state_end_pose_from_plan_arm(
      dig_linear_traj)
    cartesian_plan, fraction = plan_cartesian_path_lin(
      current_pose, length, alpha, z_start, cs)
    dig_linear_traj = _cascade_plans(dig_linear_traj, cartesian_plan)

    #  rotate to dig out
    cs, start_state, current_pose = calculate_joint_state_end_pose_from_plan_arm(
      dig_linear_traj)

    if check_for_stop("dig_linear", server_stop):
      return False

    plan_g = change_joint_value(
      cs, start_state, constants.J_DIST_PITCH, math.pi/2)
    dig_linear_traj = _cascade_plans(dig_linear_traj, plan_g)

    return dig_linear_traj

  def calculate_starting_state_grinder(plan):
    #joint_names: [j_shou_yaw, j_shou_pitch, j_prox_pitch, j_dist_pitch, j_hand_yaw, j_grinder]
    # robot full state name: [j_ant_pan, j_ant_tilt, j_shou_yaw, j_shou_pitch, j_prox_pitch, j_dist_pitch, j_hand_yaw,
    # j_grinder, j_scoop_yaw]

    start_state = plan.joint_trajectory.points[len(
      plan.joint_trajectory.points)-1].positions
    cs = self._robot.get_current_state()
    # adding antenna state (0, 0) and j_scoop_yaw  to the robot states.
    # j_scoop_yaw  state obstained from rviz
    new_value = (0, 0) + start_state[:6] + (0.17403329917811217,)
    # modify current state of robot to the end state of the previous plan
    cs.joint_state.position = new_value
    return cs, start_state

  def calculate_joint_state_end_pose_from_plan_grinder(plan):
    '''
    calculate the end pose (position and orientation), joint states and robot states
    from the current plan
    inputs:  current plan, robot, grinder interface, and moveit forward kinematics object
    outputs: goal_pose, robot state and joint states at end of the plan

    :type plan: JointTrajectory
    '''
    # get joint states from the end of the plan
    joint_states = plan.joint_trajectory.points[len(
      plan.joint_trajectory.points)-1].positions
    # construct robot state at the end of the plan
    robot_state = self._robot.get_current_state()
    # adding antenna (0,0) and j_scoop_yaw (0.1) which should not change
    new_value = (0, 0) + joint_states[:6] + (0.1740,)
    # modify current state of robot to the end state of the previous plan
    robot_state.joint_state.position = new_value
    # TODO: may raise ROSSerializationException
    goal_pose = self.compute_forward_kinematics(fkln, robot_state)
    return robot_state, joint_states, goal_pose

  def grind(args):
    """
    :type self._move_grinder: class 'moveit_commander.move_group.MoveGroupCommander'
    :type robot: class 'moveit_commander.RobotCommander'
    :type moveit_fk: class moveit_msgs/GetPositionFK
    :type args: List[bool, float, float, float, float, bool, float, bool]
    """

    x_start = args.x_start
    y_start = args.y_start
    depth = args.depth
    length = args.length
    parallel = args.parallel
    ground_position = args.ground_position

    # Compute shoulder yaw angle to trench
    alpha = math.atan2(y_start-constants.Y_SHOU, x_start-constants.X_SHOU)
    h = math.sqrt(pow(y_start-constants.Y_SHOU, 2) +
            pow(x_start-constants.X_SHOU, 2))
    l = constants.Y_SHOU - constants.HAND_Y_OFFSET
    beta = math.asin(l/h)
    alpha = alpha+beta

    if parallel:
      R = math.sqrt(x_start*x_start+y_start*y_start)
      # adjust trench to fit scoop circular motion
      dx = 0.04*R*math.sin(alpha)  # Center dig_circular in grind trench
      dy = 0.04*R*math.cos(alpha)
      # Move starting point back to avoid scoop-terrain collision
      x_start = 0.9*(x_start + dx)
      y_start = 0.9*(y_start - dy)
    else:
      dx = 5*length/8*math.sin(alpha)
      dy = 5*length/8*math.cos(alpha)
      # Move starting point back to avoid scoop-terrain collision
      x_start = 0.97*(x_start - dx)
      y_start = 0.97*(y_start + dy)

    # Place the grinder vertical, above the desired starting point, at
    # an altitude of 0.25 meters in the base_link frame.
    robot_state = self._robot.get_current_state()
    self._move_grinder.set_start_state(robot_state)
    goal_pose = self._move_grinder.get_current_pose().pose
    goal_pose.position.x = x_start  # Position
    goal_pose.position.y = y_start
    goal_pose.position.z = 0.25
    goal_pose.orientation.x = 0.70616885803  # Orientation
    goal_pose.orientation.y = 0.0303977418722
    goal_pose.orientation.z = -0.706723318474
    goal_pose.orientation.w = 0.0307192507001
    self._move_grinder.set_pose_target(goal_pose)

    if check_for_stop("grind_action", server_stop):
      return False
    _, plan_a, _, _ = self._move_grinder.plan()
    if len(plan_a.joint_trajectory.points) == 0:  # If no plan found, abort
      return False

    # entering terrain
    z_start = ground_position + constants.GRINDER_OFFSET - depth
    cs, start_state, goal_pose = calculate_joint_state_end_pose_from_plan_grinder(
      plan_a)
    plan_b = go_to_Z_coordinate(
      cs, goal_pose, x_start, y_start, z_start, False)

    grind_traj = _cascade_plans(plan_a, plan_b)

    if check_for_stop("grind_action", server_stop):
      return False

    # grinding ice forward
    cs, start_state, goal_pose = calculate_joint_state_end_pose_from_plan_grinder(
      grind_traj)
    cartesian_plan, fraction = plan_cartesian_path(
      goal_pose, length, alpha, parallel, z_start, cs)

    grind_traj = _cascade_plans(grind_traj, cartesian_plan)

    if check_for_stop("grind_action", server_stop):
      return False

    # grinding sideways
    cs, start_state, joint_goal = calculate_joint_state_end_pose_from_plan_grinder(
      grind_traj)
    if parallel:
      plan_c = change_joint_value(
        cs, start_state, constants.J_SHOU_YAW, start_state[0]+0.08)
    else:
      x_now = joint_goal.position.x
      y_now = joint_goal.position.y
      z_now = joint_goal.position.z
      x_goal = x_now + 0.08*math.cos(alpha)
      y_goal = y_now + 0.08*math.sin(alpha)
      plan_c = go_to_Z_coordinate(
        cs, joint_goal, x_goal, y_goal, z_now, False)

    if check_for_stop("grind_action", server_stop):
      return False

    grind_traj = _cascade_plans(grind_traj, plan_c)
    # grinding ice backwards
    cs, start_state, joint_goal = calculate_joint_state_end_pose_from_plan_grinder(
      grind_traj)
    cartesian_plan2, fraction2 = plan_cartesian_path(
      joint_goal, -length, alpha, parallel, z_start, cs)
    grind_traj = _cascade_plans(grind_traj, cartesian_plan2)

    if check_for_stop("grind_action", server_stop):
      return False

    # exiting terrain
    cs, start_state, joint_goal = calculate_joint_state_end_pose_from_plan_grinder(
      grind_traj)
    plan_d = go_to_Z_coordinate(
      cs, joint_goal, x_start, y_start, 0.22, False)
    grind_traj = _cascade_plans(grind_traj, plan_d)

    if check_for_stop("grind_action", server_stop):
      return False

    return grind_traj

  def guarded_move_plan(args):
    """
    :type self._move_arm: class 'moveit_commander.move_group.MoveGroupCommander'
    :type robot: class 'moveit_commander.RobotCommander'
    :type moveit_fk: class moveit_msgs/GetPositionFK
    :type args: List[bool, float, float, float, float, float, float, float]
    """

    robot_state = self._robot.get_current_state()
    self._move_arm.set_start_state(robot_state)
    self._move_arm.set_planner_id("RRTstar")

    ### pre-guarded move starts here ###

    targ_x = args.start.x
    targ_y = args.start.y
    targ_z = args.start.z
    direction_x = args.normal.x
    direction_y = args.normal.y
    direction_z = args.normal.z
    search_distance = args.search_distance

    # STUB: GROUND HEIGHT TO BE EXTRACTED FROM DEM
    targ_elevation = -0.2
    if (targ_z+targ_elevation) == 0:
      offset = search_distance
    else:
      offset = (targ_z*search_distance)/(targ_z+targ_elevation)

    # Compute shoulder yaw angle to target
    alpha = math.atan2((targ_y+direction_y*offset)-constants.Y_SHOU,
               (targ_x+direction_x*offset)-constants.X_SHOU)
    h = math.sqrt(pow((targ_y+direction_y*offset)-constants.Y_SHOU, 2) +
            pow((targ_x+direction_x*offset)-constants.X_SHOU, 2))
    l = constants.Y_SHOU - constants.HAND_Y_OFFSET
    beta = math.asin(l/h)

    # Move to pre move position, align shoulder yaw
    joint_goal = self._move_arm.get_current_joint_values()
    joint_goal[constants.J_DIST_PITCH] = 0
    joint_goal[constants.J_HAND_YAW] = 0
    joint_goal[constants.J_PROX_PITCH] = -math.pi/2
    joint_goal[constants.J_SHOU_PITCH] = math.pi/2
    joint_goal[constants.J_SHOU_YAW] = alpha + beta

    # If out of joint range, abort
    if (is_shou_yaw_goal_in_range(joint_goal) == False):
      return False, False

    joint_goal[constants.J_SCOOP_YAW] = 0

    self._move_arm.set_joint_value_target(joint_goal)

    if check_for_stop("guarded_move", server_stop):
      return False, False

    _, plan_a, _, _ = self._move_arm.plan()
    if len(plan_a.joint_trajectory.points) == 0:  # If no plan found, abort
      return False, False

    # Once aligned to move goal and offset, place scoop tip at surface target offset
    cs, start_state, goal_pose = calculate_joint_state_end_pose_from_plan_arm(
      plan_a)
    self._move_arm.set_start_state(cs)
    goal_pose.position.x = targ_x
    goal_pose.position.y = targ_y
    goal_pose.position.z = targ_z

    self._move_arm.set_pose_target(goal_pose)

    if check_for_stop("guarded_move", server_stop):
      return False, False

    _, plan_b, _, _ = self._move_arm.plan()
    if len(plan_b.joint_trajectory.points) == 0:  # If no plan found, abort
      return False, False
    pre_guarded_move_traj = _cascade_plans(plan_a, plan_b)

    ### pre-guarded move ends here ###

    # Drive scoop tip along norm vector, distance is search_distance

    cs, start_state, goal_pose = calculate_joint_state_end_pose_from_plan_arm(
      pre_guarded_move_traj)
    self._move_arm.set_start_state(cs)
    goal_pose.position.x = targ_x
    goal_pose.position.y = targ_y
    goal_pose.position.z = targ_z
    goal_pose.position.x -= direction_x*search_distance
    goal_pose.position.y -= direction_y*search_distance
    goal_pose.position.z -= direction_z*search_distance

    self._move_arm.set_pose_target(goal_pose)

    if check_for_stop("guarded_move", server_stop):
      return False, False

    _, plan_c, _, _ = self._move_arm.plan()

    guarded_move_traj = _cascade_plans(pre_guarded_move_traj, plan_c)
    self._move_arm.set_planner_id("RRTconnect")
    '''
    estimated time ratio is the ratio between the time to complete first two parts of the plan
    to the the entire plan. It is used for ground detection only during the last part of the plan.
    It is set at 0.5 after several tests
    '''

    estimated_time_ratio =0.5
    return guarded_move_traj, estimated_time_ratio

  def discard_sample(args):
    """
    :type self._move_arm: class 'moveit_commander.move_group.MoveGroupCommander'
    :type robot: class 'moveit_commander.RobotCommander'
    :type moveit_fk: class moveit_msgs/GetPositionFK
    :type args: List[bool, float, float, float]
    """
    robot_state = self._robot.get_current_state()
    self._move_arm.set_start_state(robot_state)
    x_discard = args.discard.x
    y_discard = args.discard.y
    z_discard = args.discard.z

    # after sample collect
    mypi = 3.14159
    d2r = mypi/180
    r2d = 180/mypi

    goal_pose = self._move_arm.get_current_pose().pose
    # position was found from rviz tool
    goal_pose.position.x = x_discard
    goal_pose.position.y = y_discard
    goal_pose.position.z = z_discard

    r = -179
    p = -20
    y = -90

    q = quaternion_from_euler(r*d2r, p*d2r, y*d2r)
    goal_pose.orientation = Quaternion(q[0], q[1], q[2], q[3])

    self._move_arm.set_pose_target(goal_pose)
    self._move_arm.set_planner_id("RRTstar")
    if check_for_stop("discard_sample", server_stop):
      return False
    _, plan_a, _, _ = self._move_arm.plan()

    if len(plan_a.joint_trajectory.points) == 0:  # If no plan found, abort
      return False

    # adding position constraint on the solution so that the tip doesnot diverge to get to the solution.
    pos_constraint = PositionConstraint()
    pos_constraint.header.frame_id = "base_link"
    pos_constraint.link_name = "l_scoop"
    pos_constraint.target_point_offset.x = 0.1
    pos_constraint.target_point_offset.y = 0.1
    # rotate scoop to discard sample at current location begin
    pos_constraint.target_point_offset.z = 0.1
    pos_constraint.constraint_region.primitives.append(
      SolidPrimitive(type=SolidPrimitive.SPHERE, dimensions=[0.01]))
    pos_constraint.weight = 1

    # using euler angles for own verification..

    r = +180
    p = 90
    y = -90
    q = quaternion_from_euler(r*d2r, p*d2r, y*d2r)

    cs, start_state, goal_pose = calculate_joint_state_end_pose_from_plan_arm(
      robot, plan_a, self._move_arm, moveit_fk)

    self._move_arm.set_start_state(cs)

    goal_pose.orientation = Quaternion(q[0], q[1], q[2], q[3])

    self._move_arm.set_pose_target(goal_pose)
    if check_for_stop("discard_sample", server_stop):
      return False
    _, plan_b, _, _ = self._move_arm.plan()

    # If no plan found, send the previous plan only
    if len(plan_b.joint_trajectory.points) == 0:
      return plan_a

    discard_sample_traj = _cascade_plans(plan_a, plan_b)
    self._move_arm.set_planner_id("RRTconnect")
    return discard_sample_traj

  def deliver_sample():
    """
    :type self._move_arm: class 'moveit_commander.move_group.MoveGroupCommander'
    :type robot: class 'moveit_commander.RobotCommander'
    :type moveit_fk: class moveit_msgs/GetPositionFK
    """
    total_plan = None
    targets = [
      "arm_deliver_staging_1",
      "arm_deliver_staging_2",
      "arm_deliver_final"
    ]
    for t in targets:
      cs = self._robot.get_current_state() if total_plan is None else \
        calculate_joint_state_end_pose_from_plan_arm(
          robot, total_plan, self._move_arm, moveit_fk)[0]
      self._move_arm.set_start_state(cs)
      self._move_arm.set_planner_id("RRTstar")
      goal = self._move_arm.get_named_target_values(t)
      self._move_arm.set_joint_value_target(goal)

      if check_for_stop("deliver_sample", server_stop):
        return False

      _, plan, _, _ = self._move_arm.plan()
      if len(plan.joint_trajectory.points) == 0:
        return False
      total_plan = plan if total_plan is None else \
        _cascade_plans(total_plan, plan)
    self._move_arm.set_planner_id("RRTconnect")
    return total_plan

def _cascade_plans(plan1, plan2):
  '''
  Joins two robot motion plans into one
  inputs:  two robot trajactories
  outputs: final robot trjactory
  '''
  # Create a new trajectory object
  new_traj = RobotTrajectory()
  # Initialize the new trajectory to be the same as the planned trajectory
  traj_msg = JointTrajectory()
  # Get the number of joints involved
  n_joints1 = len(plan1.joint_trajectory.joint_names)
  n_joints2 = len(plan2.joint_trajectory.joint_names)
  # Get the number of points on the trajectory
  n_points1 = len(plan1.joint_trajectory.points)
  n_points2 = len(plan2.joint_trajectory.points)
  # Store the trajectory points
  points1 = list(plan1.joint_trajectory.points)
  points2 = list(plan2.joint_trajectory.points)
  end_time = plan1.joint_trajectory.points[n_points1-1].time_from_start
  start_time = plan1.joint_trajectory.points[0].time_from_start
  duration = end_time - start_time
  # add a time toleracne between  successive plans
  time_tolerance = rospy.Duration.from_sec(0.1)

  for i in range(n_points1):
    point = JointTrajectoryPoint()
    point.time_from_start = plan1.joint_trajectory.points[i].time_from_start
    point.velocities = list(
      plan1.joint_trajectory.points[i].velocities)
    point.accelerations = list(
      plan1.joint_trajectory.points[i].accelerations)
    point.positions = plan1.joint_trajectory.points[i].positions
    points1[i] = point
    traj_msg.points.append(point)
    end_time = plan1.joint_trajectory.points[i].time_from_start

  for i in range(n_points2):
    point = JointTrajectoryPoint()
    point.time_from_start = plan2.joint_trajectory.points[i].time_from_start + \
      end_time + time_tolerance
    point.velocities = list(
      plan2.joint_trajectory.points[i].velocities)
    point.accelerations = list(
      plan2.joint_trajectory.points[i].accelerations)
    point.positions = plan2.joint_trajectory.points[i].positions
    traj_msg.points.append(point)

  traj_msg.joint_names = plan1.joint_trajectory.joint_names
  traj_msg.header.frame_id = plan1.joint_trajectory.header.frame_id
  new_traj.joint_trajectory = traj_msg
  return new_traj
