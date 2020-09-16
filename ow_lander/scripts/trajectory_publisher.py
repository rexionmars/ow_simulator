#!/usr/bin/env python

# The Notices and Disclaimers for Ocean Worlds Autonomy Testbed for Exploration
# Research and Simulation can be found in README.md in the root directory of
# this repository.

import rospy
import tf2_ros
from std_msgs.msg import Float64
from geometry_msgs.msg import Point
from sensor_msgs.msg import JointState
from gazebo_msgs.msg import LinkStates
from ow_lander.srv import *
import csv
import time
import glob
import os
import constants
import numpy as np
from ow_lander.msg import GuardedMoveResult

# TODO: rather than basing the decision on a single value we can take the trend
# over a short term of position z value it would probably make the implementation
# more robust against an arm physics configuration where the end effector doesn't
#  bounce off the ground at all.

# constanst
GROUND_DETECTION_THRESHOLD = 0.001  # TODO: tune this value further to improve the detection
                                    # .. need to test with various configurations too
ground_detected = 0
last_scoop_tip_pos_z = None

def handle_link_states(data):
  global ground_detected, last_scoop_tip_pos_z

  if ground_detected:
    return

  try:
    idx = data.name.index("lander::l_scoop_tip")
  except ValueError:
    rospy.logerr_throttle(1, "lander::l_scoop_tip not found in link_states")
    return

  if last_scoop_tip_pos_z is None:
    last_scoop_tip_pos_z = data.pose[idx].position.z
    return

  current_scoop_tip_z = data.pose[idx].position.z
  delta = current_scoop_tip_z - last_scoop_tip_pos_z
  last_scoop_tip_pos_z = current_scoop_tip_z

  if delta > GROUND_DETECTION_THRESHOLD:
    ground_detected = 1
  

# The talker runs once the publish service is called. It starts a publisher
# per joint controller, then reads the trajectory csvs.
# If the traj csv is a guarded move, it reads both parts.
# When publishing the safe (second) part of a guarded_move, it
# monitors the velocity, and cuts off the publishing after is ground is detected.
#The ground is detected after the peak_detection algorithm detects a spike in the velocity data


def talker(req):
  pubs = []
  pubs.append(rospy.Publisher('/shou_yaw_position_controller/command', Float64, queue_size=40))
  pubs.append(rospy.Publisher('/shou_pitch_position_controller/command', Float64, queue_size=40))
  pubs.append(rospy.Publisher('/prox_pitch_position_controller/command', Float64, queue_size=40))
  pubs.append(rospy.Publisher('/dist_pitch_position_controller/command', Float64, queue_size=40))
  pubs.append(rospy.Publisher('/hand_yaw_position_controller/command', Float64, queue_size=40))
  pubs.append(rospy.Publisher('/scoop_yaw_position_controller/command', Float64, queue_size=40))
  pub_rate = constants.TRAJ_PUB_RATE # Hz
  rate = rospy.Rate(pub_rate) # Hz
  nb_links = constants.NB_ARM_LINKS
  rows = []
  guard_rows = []
  guarded_move_bool = False


  # === READ TRAJ FILE(S) ===============================
  if req.use_latest:
    files = glob.glob('*.csv')
    filename = max(files, key=os.path.getctime)
  else :
    filename = req.trajectory_filename

  #TODO: Add file check on trajectory
  print "Start publishing trajectory with filename = %s"%(filename)

  # Use two files instead of one if this is a guarded move
  if filename.startswith('guarded_move_traj_'):
    # reading csv file
    guard_filename = filename
    prefix = "pre_"
    filename = prefix + filename
    guarded_move_bool = True

  # Reading csv file
  with open(filename, 'r') as csvfile:
    # creating a csv reader object
    csvreader = csv.reader(csvfile)

    # extracting each data row one by one
    for row in csvreader:
      rows.append(row)

  # If guarded_move, read the guarded motion traj csv
  if guarded_move_bool :
    with open(guard_filename, 'r') as csvfile:
      # creating a csv reader object
      csvreader = csv.reader(csvfile)

      # extracting each data row one by one
      for row in csvreader:
        guard_rows.append(row)

  # === PUBLISH TRAJ FILE(S) ===============================
  for row in rows[1:]: # Cycles on all the rows except header
    if row[0][0] == '1' : # If the row is a command
      for x in range(nb_links):
        pubs[x].publish(float("%14s\n"%row[12+x]))
      rate.sleep()


  if guarded_move_bool : # If the activity is a guarded_move

    # Start publisher for guarded_move result message
    guarded_move_pub = rospy.Publisher('/guarded_move_result', GuardedMoveResult, queue_size=10)

    # Start subscriber for the joint_states
    time.sleep(2) # wait for 2 seconds till the arm settles
    # begin tracking velocity values as soon as the scoop moves downward 
    global ground_detected, last_scoop_tip_pos_z
    ground_detected = 0
    last_scoop_tip_pos_z = None
    rate = rospy.Rate(int(pub_rate/2)) # Hz
    rospy.Subscriber("/gazebo/link_states", LinkStates, handle_link_states)
    tfBuffer = tf2_ros.Buffer()
    _ = tf2_ros.TransformListener(tfBuffer)

    for row in guard_rows[1:]: # Cycles on all the rows except header
      if row[0][0] == '1' : # If the row is a command
        if ground_detected != 0:
          print "Found ground, stopped motion..."

          trans = tfBuffer.lookup_transform("base_link", "l_scoop_tip", rospy.Time(0), rospy.Duration(10.0))
          guarded_move_pub.publish(True, trans.transform.translation, 'base_link')

          return True, "Done publishing guarded_move"

        for x in range(nb_links):
          pubs[x].publish(float("%14s\n"%row[12+x]))
        rate.sleep()

    guarded_move_pub.publish(False, Point(0.0, 0.0, 0.0), 'base_link')

  return True, "Done publishing trajectory"


if __name__ == '__main__':
  rospy.init_node('trajectory_publisher', anonymous=True)
  start_srv = rospy.Service('arm/publish_trajectory', PublishTrajectory, talker)
  rospy.spin()
