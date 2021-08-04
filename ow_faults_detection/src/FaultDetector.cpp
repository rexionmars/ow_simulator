// The Notices and Disclaimers for Ocean Worlds Autonomy Testbed for Exploration
// Research and Simulation can be found in README.md in the root directory of
// this repository.

#include "ow_faults_detection/FaultDetector.h"
#include <algorithm>

using namespace std;
using namespace ow_lander;

constexpr std::bitset<10> FaultDetector::isCamExecutionError;
constexpr std::bitset<10> FaultDetector::isPanTiltExecutionError;
constexpr std::bitset<10> FaultDetector::isArmExecutionError;
constexpr std::bitset<10> FaultDetector::isPowerSystemFault;

constexpr std::bitset<3> FaultDetector::islowVoltageError;
constexpr std::bitset<3> FaultDetector::isCapLossError;
constexpr std::bitset<3> FaultDetector::isThermalError;

FaultDetector::FaultDetector(ros::NodeHandle& node_handle)
{
  srand (static_cast <unsigned> (time(0)));
  // arm
  m_arm_joint_states_sub = node_handle.subscribe( "/joint_states",
                                          10,
                                          &FaultDetector::armJointStatesCb,
                                          this);
  m_arm_controller_states_sub = node_handle.subscribe( "/arm_controller/state",
                                          10,
                                          &FaultDetector::armControllerStateCb,
                                          this);
  // antenna
  auto original_str = "/_original";
  auto ant_pan_str = "/ant_pan_position_controller";
  auto ant_tilt_str = "/ant_tilt_position_controller";
  m_ant_pan_command_sub = node_handle.subscribe( string("/_original") + ant_pan_str + string("/command"),
                                          10,
                                          &FaultDetector::antennaPanCommandCb,
                                          this);
  m_ant_pan_state_sub = node_handle.subscribe(ant_pan_str + string("/state"),
                                          10,
                                          &FaultDetector::antennaPanStateCb,
                                          this);
  m_ant_tilt_command_sub = node_handle.subscribe( string("/_original") + ant_tilt_str + string("/command"),
                                          10,
                                          &FaultDetector::antennaTiltCommandCb,
                                          this);
  m_ant_tilt_state_sub = node_handle.subscribe(ant_tilt_str + string("/state"),
                                          10,
                                          &FaultDetector::antennaTiltStateCb,
                                          this);
  // camera
  auto image_trigger_str = "/StereoCamera/left/image_trigger";
  m_camera_original_trigger_sub = node_handle.subscribe(string("/_original") + image_trigger_str,
    10, &FaultDetector::cameraTriggerOriginalCb, this);
  m_camera_trigger_sub = node_handle.subscribe(image_trigger_str,
    10, &FaultDetector::cameraTriggerCb, this);
  m_camera_trigger_timer = node_handle.createTimer(ros::Duration(0.1), &FaultDetector::cameraTriggerPublishCb, this);

  //  power fault publishers and subs
  m_power_soc_sub = node_handle.subscribe("/power_system_node/state_of_charge",
                                          10,
                                          &FaultDetector::powerSOCListener,
                                          this);
  m_power_temperature_sub = node_handle.subscribe("/power_system_node/battery_temperature",
                                                  10,
                                                  &FaultDetector::powerTemperatureListener,
                                                  this);

  // topics for JPL msgs: system fault messages, see Faults.msg, Arm.msg, Power.msg, PTFaults.msg
  m_arm_fault_msg_pub = node_handle.advertise<ow_faults::ArmFaults>("/faults/arm_faults_status", 10);
  m_antenna_fault_msg_pub = node_handle.advertise<ow_faults::PTFaults>("/faults/pt_faults_status", 10);
  m_camera_fault_msg_pub = node_handle.advertise<ow_faults::CamFaults>("/faults/cam_faults_status", 10);
  m_power_fault_msg_pub = node_handle.advertise<ow_faults::PowerFaults>("/faults/power_faults_status", 10);
  m_system_fault_msg_pub = node_handle.advertise<ow_faults::SystemFaults>("/faults/system_faults_status", 10);

}

// Creating Fault Messages
template<typename fault_msg>
void FaultDetector::setFaultsMessageHeader(fault_msg& msg){
  msg.header.stamp = ros::Time::now();
  msg.header.frame_id = "world";
}

template<typename bitsetFaultsMsg, typename bitmask>
void FaultDetector::setBitsetFaultsMessage(bitsetFaultsMsg& msg, bitmask bm) {
  setFaultsMessageHeader(msg);
  msg.value = bm.to_ullong();
}

template<typename fault_msg>
void FaultDetector::setComponentFaultsMessage(fault_msg& msg, ComponentFaults value) {
  setFaultsMessageHeader(msg);
  msg.value = static_cast<uint>(value);
}

// publish system messages
void FaultDetector::publishSystemFaultsMessage(){
  ow_faults::SystemFaults system_faults_msg;
  setBitsetFaultsMessage(system_faults_msg, m_system_faults_bitset);
  m_system_fault_msg_pub.publish(system_faults_msg);
}

//// Publish Camera Messages
void FaultDetector::cameraTriggerPublishCb(const ros::TimerEvent& t){
  ow_faults::CamFaults camera_faults_msg;

  if (m_cam_og_trigger_time != m_cam_trigger_time) {
    m_system_faults_bitset |= isCamExecutionError;
    setComponentFaultsMessage(camera_faults_msg, ComponentFaults::Hardware);
  } else {
    m_system_faults_bitset &= ~isCamExecutionError;
  }

  publishSystemFaultsMessage();
  m_camera_fault_msg_pub.publish(camera_faults_msg);
}

//// Publish Power Faults Messages
void FaultDetector::publishPowerSystemFault(){
  ow_faults::PowerFaults power_faults_msg;
  //update if fault
  if (m_temperature_fault || m_soc_fault) {
    //system
    m_system_faults_bitset |= isPowerSystemFault;
    //power
    setComponentFaultsMessage(power_faults_msg, ComponentFaults::Hardware);
  } else {
    m_system_faults_bitset &= ~isPowerSystemFault;
  }
  publishSystemFaultsMessage();
  m_power_fault_msg_pub.publish(power_faults_msg);
}

// Listeners
// Arm listeners
void FaultDetector::armControllerStateCb(const control_msgs::JointTrajectoryControllerState::ConstPtr& msg){
  int i = 0;
  for (auto it : msg->joint_names){
    m_current_arm_positions[it] = msg->actual.positions[i];
    // cout << m_current_arm_positions["j_shou_yaw"] << endl;
    i++;
  }
}

void FaultDetector::armJointStatesCb(const sensor_msgs::JointStateConstPtr& msg){
  // Populate the map once here.
  // This assumes the collection of joints will never change.
  if (m_joint_state_indices.empty()) {
    for (int j = 0; j < NUM_JOINTS; j ++) {
      int index = findPositionInGroup(msg->name, joint_names[j]);
      if (index >= 0)
        m_joint_state_indices.push_back(index);
    }
  }
  bool arm_fault = false;
  

  // if (findJointIndex(J_SHOU_YAW, index)) {
  //   if (msg->position[index]  == FAULT_ZERO_TELEMETRY || msg->effort[index]  == FAULT_ZERO_TELEMETRY){
  //     if (joint_names[J_SHOU_YAW] == msg->name[index]) {
  //       // arm_fault = true;
  //        cout << "message name of index " << msg->name[index] << endl;
  //         cout << "jointname name of J_SHOU_YAW " << joint_names[J_SHOU_YAW] << endl;
  //         cout << " index " << index << " position: " << msg->position[index] << " effort: " << msg->effort[index]  << endl;
  //     }
  //   }
  // }
  // if (findJointIndex(J_SHOU_PITCH, index)) {
  //   if (msg->position[index]  == FAULT_ZERO_TELEMETRY || msg->effort[index]  == FAULT_ZERO_TELEMETRY){
  //     if (joint_names[J_SHOU_PITCH] == msg->name[index]) {
  //       // arm_fault = true;
  //       cout << "message name of index " << msg->name[index] << endl;
  //       cout << "jointname name of J_SHOU_PITCH " << joint_names[J_SHOU_PITCH] << endl;
  //       cout << " index " << index << " position: " << msg->position[index] << " effort: " << msg->effort[index]  << endl;
  //     }
  //   }
  // }
  // if (findJointIndex(J_PROX_PITCH, index)) {
  //   if (msg->position[index]  == FAULT_ZERO_TELEMETRY || msg->effort[index]  == FAULT_ZERO_TELEMETRY){
  //     if (joint_names[J_PROX_PITCH] == msg->name[index]) {
  //       // arm_fault = true;
  //       cout << "message name of index " << msg->name[index] << endl;
  //       cout << "jointname name of J_PROX_PITCH " << joint_names[J_PROX_PITCH] << endl;
  //       cout << " index " << index << " position: " << msg->position[index] << " effort: " << msg->effort[index]  << endl;
  //     }
  //   }
  // }
  // if (findJointIndex(J_DIST_PITCH, index)) {
  //   if (msg->position[index]  == FAULT_ZERO_TELEMETRY || msg->effort[index]  == FAULT_ZERO_TELEMETRY){
  //     if (joint_names[J_DIST_PITCH] == msg->name[index]) {
  //       // arm_fault = true;
  //       cout << "message name of index " << msg->name[index] << endl;
  //       cout << "jointname name of J_DIST_PITCH " << joint_names[J_DIST_PITCH] << endl;
  //       cout << " index " << index << " position: " << msg->position[index] << " effort: " << msg->effort[index]  << endl;
  //     }
  //   }
  // }
  // if (findJointIndex(J_HAND_YAW, index)) {
  //   if (msg->position[index]  == FAULT_ZERO_TELEMETRY || msg->effort[index]  == FAULT_ZERO_TELEMETRY){
  //     if (joint_names[J_HAND_YAW] == msg->name[index]) {
  //       // arm_fault = true;
  //       cout << "message name of index " << msg->name[index] << endl;
  //       cout << "jointname name of J_HAND_YAW " << joint_names[J_HAND_YAW] << endl;
  //       cout << "position 4  " << msg->position[4] << endl;
  //       cout << " index " << index << " position: " << msg->position[index] << " effort: " << msg->effort[index]  << endl;
  //     }
  //   }
  // }
  arm_fault = findArmFault( J_HAND_YAW, msg->name, msg->position, msg->effort) && findArmFault( J_SCOOP_YAW, msg->name, msg->position, msg->effort);
  // if (findJointIndex(J_SCOOP_YAW, index) && joint_names[J_SCOOP_YAW] == msg->name[index]) {
  //   if (msg->position[index]  == FAULT_ZERO_TELEMETRY ){
  //     if (m_current_arm_positions[joint_names[J_SCOOP_YAW]] != msg->position[index]) {
  //         arm_fault = true;
  //         cout << "message name of index " << msg->name[index] << endl;
  //         // cout << "jointname name of J_SCOOP_YAW " << joint_names[J_SCOOP_YAW] << endl;
  //         cout << "real position " << m_current_arm_positions[joint_names[J_SCOOP_YAW]] << " msg position " << msg->position[index] << endl;
  //         cout << " index " << index << " position: " << msg->position[index] << " effort: " << msg->effort[index]  << endl;
  //       }
  //   }
  //   if (msg->effort[index]  == FAULT_ZERO_TELEMETRY){
  //       arm_fault = true;
  //       cout << "message name of index " << msg->name[index] << endl;
  //       // cout << "jointname name of J_SCOOP_YAW " << joint_names[J_SCOOP_YAW] << endl;
  //       cout << "real position " << m_current_arm_positions[joint_names[J_SCOOP_YAW]] << " msg position " << msg->position[index] << endl;
  //       cout << " index " << index << " position: " << msg->position[index] << " effort: " << msg->effort[index]  << endl;
  //   }
  // }
  
  ow_faults::ArmFaults arm_faults_msg;
  if (arm_fault) {
    m_system_faults_bitset |= isArmExecutionError;
    setComponentFaultsMessage(arm_faults_msg, ComponentFaults::Hardware);
  } else {
    m_system_faults_bitset &= ~isArmExecutionError;
  }
  m_arm_fault_msg_pub.publish(arm_faults_msg);
  publishSystemFaultsMessage();

}

template<typename names, typename positions, typename effort>
bool FaultDetector::findArmFault(int jointName, names n, positions pos, effort eff){
  unsigned int index;
  bool result;
  if (findJointIndex(jointName, index) && joint_names[jointName] == n[index]) {
    if (pos[index]  == FAULT_ZERO_TELEMETRY ){
      // if (m_current_arm_positions[joint_names[jointName]] != pos[index]) {
          result = true;
          cout << "message name of index " << n[index] << endl;
          // cout << "jointname name of jointName " << joint_names[jointName] << endl;
          cout << "real position " << m_current_arm_positions[joint_names[jointName]] << " msg position " << pos[index] << endl;
          cout << " index " << index << " position: " << pos[index] << " effort: " << eff[index]  << endl;
        // }
    }
    if (eff[index]  == FAULT_ZERO_TELEMETRY){
        result = true;
        cout << "message name of index " << n[index] << endl;
        // cout << "jointname name of jointName " << joint_names[jointName] << endl;
        cout << "real position " << m_current_arm_positions[joint_names[jointName]] << " msg position " << pos[index] << endl;
        cout << " index " << index << " position: " << pos[index] << " effort: " << eff[index]  << endl;
    }
  }
  return result;
}

template<typename group_t, typename item_t>
int FaultDetector::findPositionInGroup(const group_t& group, const item_t& item)
{
  auto iter = std::find(group.begin(), group.end(), item);
  if (iter == group.end())
    return -1;
  return iter - group.begin();
}

bool FaultDetector::findJointIndex(const unsigned int joint, unsigned int& out_index)
{
  if(joint >= NUM_JOINTS)
    return false;

  out_index = m_joint_state_indices[joint];
  return true;
}

//// Antenna Listeners
void FaultDetector::antennaPanCommandCb(const std_msgs::Float64& msg){
  antPublishFaultMessages( msg.data, m_ant_pan_set_point);
}

void FaultDetector::antennaTiltCommandCb(const std_msgs::Float64& msg){
  antPublishFaultMessages(msg.data, m_ant_tilt_set_point);
}

void FaultDetector::antPublishFaultMessages(float command, float m_set_point ){
  ow_faults::PTFaults ant_pan_fault_msg;

  if (command != m_set_point) {
    setComponentFaultsMessage(ant_pan_fault_msg, ComponentFaults::Hardware);
    m_system_faults_bitset |= isPanTiltExecutionError;
  }else {
    m_system_faults_bitset &= ~isPanTiltExecutionError;
  }
  publishSystemFaultsMessage();
  m_antenna_fault_msg_pub.publish(ant_pan_fault_msg);
}

void FaultDetector::antennaPanStateCb(const control_msgs::JointControllerState& msg){
  m_ant_pan_set_point = msg.set_point;
}

void FaultDetector::antennaTiltStateCb(const control_msgs::JointControllerState& msg){
  m_ant_tilt_set_point = msg.set_point;
}

//// Camera listeners
void FaultDetector::cameraTriggerOriginalCb(const std_msgs::Empty& msg){
  m_cam_og_trigger_time = ros::Time::now();
}

void FaultDetector::cameraTriggerCb(const std_msgs::Empty& msg){
  m_cam_trigger_time = ros::Time::now();
}

//// Power Topic Listeners
void FaultDetector::powerTemperatureListener(const std_msgs::Float64& msg)
{
  m_temperature_fault = msg.data > THERMAL_MAX;
  publishPowerSystemFault();
}

void FaultDetector::powerSOCListener(const std_msgs::Float64& msg)
{
  float newSOC = msg.data;
  if (isnan(m_last_SOC)){
    m_last_SOC = newSOC;
  }
  m_soc_fault = ((newSOC <= SOC_MIN)  ||
        (!isnan(m_last_SOC) &&
        ((abs(m_last_SOC - newSOC) / m_last_SOC) >= SOC_MAX_DIFF )));
  publishPowerSystemFault();
  m_last_SOC = newSOC;
}

// helper functions
float FaultDetector::getRandomFloatFromRange( float min_val, float max_val){
  return min_val + (max_val - min_val) * (rand() / static_cast<float>(RAND_MAX));
}
