#!/usr/bin/env python3

import rospy
import rospkg
from gazebo_msgs.srv import SpawnModel
from geometry_msgs.msg import Pose
from yaml import safe_load
from tf.transformations import quaternion_from_euler
from math import pi
import random
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Model:
    # name of the file (without ending)
    name: str

    # 'box', 'sphere', 'urdf' or 'sdf'
    type: str

    # base path inside the package, defaults to "models"
    base_path: str = 'models'

    # unique name (will be generated if not set)
    unique_name: str = None

    # name of the ROS package (empty for "box")
    package: str = ''

    # defines if the pose rotation is a quaternion or a list of euler angles
    quaternion: bool = False

    # we assume pitch yaw an roll in degree if quaternions are NOT used,
    # so we need to convert to radians
    radians: bool = False

    # position and orientation of the object in the world
    # (quaternion or pitch, roll, yaw vector)
    pose: list = None

    # scale of the object
    # (will not be used if None, otherwise a vector with depth, width, height)
    scale: list = None


def rename_duplicates( old ):
    """
    Append count numbers to duplicate names in a list
    So new list only contains unique names
    """
    seen = {}
    for x in old:
        if x in seen:
            seen[x] += 1
            yield "%s_%d" % (x, seen[x])
        else:
            seen[x] = 0
            yield x

def parse_yaml(package_name,yaml_relative_path):
    """ Parse a yaml into a dict of objects containing all data to spawn models
        Args:
        name of the package (string, refers to package where yaml file is located)
        name and path of the yaml file (string, relative path + complete name incl. file extension)
        Returns: dictionary with model objects
    """
    complete_path = Path(rospkg.RosPack().get_path(package_name))
    if yaml_relative_path[0] == '/':
        yaml_relative_path = yaml_relative_path[1:]
    complete_path /= yaml_relative_path
    f = open(complete_path, 'r')
    # populate dictionary that equals to the yaml file tree data
    yaml_dict = safe_load(f)

    modelNames = []
    for k in range(len(yaml_dict['models'])):
        model_data = yaml_dict['models'][k]
        if 'unique_name' in model_data:
            modelNames.append(model_data['unique_name'])
        else:
            modelNames.append(model_data['name'])

    # create new list with count numbers on all names that were duplicated
    modelNamesUnique = list(rename_duplicates(modelNames))
    
    rospy.loginfo("List of model names: %s" % modelNamesUnique)
    rospy.logdebug("Total number of models: ", len(yaml_dict['models']))

    # start with an empty dict where the key is the model name
    model_dict = {}
    # create list containing all nested dictionaries that hold data about each model   
    list_of_dict = [x for x in yaml_dict['models']]
    # parse YAML dictionary entries to Model class object attributes
    for idx, name in enumerate(modelNamesUnique):
        args = list_of_dict[idx]
        model_dict[name] = Model(**args)  # fill the dict with models

    # add a unique model name that can be used to spawn an model in simulation
    count = 0
    for dict_key, mod_obj in model_dict.items():
        if not mod_obj.unique_name:
            mod_obj.unique_name = modelNamesUnique[count] # add attribute 'unique_name'
            count += 1

    return model_dict

def spawn_model(model_object):
    """ Spawns a model in a particular position and orientation
        Args:
        - model object containing name, type, package and pose of the model
        Returns: None
    """
    ## unpack object attributes
    package_name = model_object.package
    spawn_pose = Pose()
    spawn_pose.position.x = model_object.pose[0]
    spawn_pose.position.y = model_object.pose[1]
    spawn_pose.position.z = model_object.pose[2]
    if model_object.quaternion:
        quat = model_object.pose[3:]
    else:
        # conversion from Euler angles (RPY) in degrees or radians
        roll = model_object.pose[3]
        pitch = model_object.pose[4]
        yaw = model_object.pose[5]
        if not model_object.radians:
            degrees2rad = pi / 180.0
            roll *= degrees2rad
            pitch *= degrees2rad
            yaw *= degrees2rad
        # create list that contains conversion from Euler to Quaternions
        quat = quaternion_from_euler(roll, pitch, yaw)
    spawn_pose.orientation.x = quat[0]
    spawn_pose.orientation.y = quat[1]
    spawn_pose.orientation.z = quat[2]
    spawn_pose.orientation.w = quat[3]
    
    # Spawn SDF model
    if model_object.type == 'sdf':
        try:
            model_path = Path(rospkg.RosPack().get_path(package_name))
            model_path /= model_object.base_path
            model_xml = ''
        except rospkg.ResourceNotFound as e:
            rospy.logerr("Cannot find package [%s], check package name and that package exists, error message:  %s"%(package_name, e))

        try:
            with open(model_path / model_object.name / 'model.sdf', 'r') as xml_file:
                model_xml = xml_file.read().replace('\n', '')
        except IOError as err:
            rospy.logerr("Cannot find or open model [1] [%s], check model name and that model exists, I/O error message:  %s"%(model_object.name,err))
        except UnboundLocalError as error:
            rospy.logdebug("Cannot find package [%s], check package name and that package exists, error message:  %s"%(package_name, error))

        try:
            rospy.logdebug("Waiting for service gazebo/spawn_sdf_model")
            # block max. 5 seconds until the service is available
            rospy.wait_for_service('gazebo/spawn_sdf_model',5.0)
            # create a handle for calling the service
            spawn_model_prox = rospy.ServiceProxy('gazebo/spawn_sdf_model', SpawnModel)
        except (rospy.ServiceException, rospy.ROSException) as e:
            rospy.logerr("Service call failed: %s" % (e,))

    elif model_object.type == "urdf":
        try:
            model_path = Path(rospkg.RosPack().get_path(package_name)) / 'urdf'
            file_xml = open(model_path / model_object.name + '.' + model_object.type, 'r')
            model_xml = file_xml.read()
        except IOError as err:
            rospy.logerr("Cannot find model [2] [%s], check model name and that model exists, I/O error message:  %s"%(model_object.name,err))
        except UnboundLocalError as error:
            rospy.logdebug("Cannot find package [%s], check package name and that package exists, error message:  %s"%(package_name, error))

        try:
            rospy.logdebug("Waiting for service gazebo/spawn_urdf_model")
            # block max. 5 seconds until the service is available
            rospy.wait_for_service('gazebo/spawn_urdf_model')
            # create a handle for calling the service
            spawn_model_prox = rospy.ServiceProxy('/gazebo/spawn_urdf_model', SpawnModel)
        except (rospy.ServiceException, rospy.ROSException) as e:
            rospy.logerr("Service call failed: %s" % (e,))

    else:
        rospy.logerr("Error: Model type not know, model_type = " + model_object.type)

    try:
        # use handle / local proxy just like a normal function and call it
        print("Now spawning: %s" % model_object.unique_name)
        res = spawn_model_prox(model_object.unique_name,model_xml, '',spawn_pose, 'world')
        # evaluate response
        if res.success == True:
            # SpawnModel: Successfully spawned entity 'model_name'
            rospy.loginfo(res.status_message + " " + model_object.name + " as " + model_object.unique_name)
        else:
            rospy.logerr("Error: model %s not spawn, error message = "% model_object.name + res.status_message)
    except UnboundLocalError as error:
        rospy.logdebug("Cannot find package [%s], check package name and that package exists, error message:  %s"%(package_name, error))

if __name__ == '__main__':

    # ROS node initialization
    rospy.init_node('object_spawner_node', log_level=rospy.INFO)

    ###### usage example
    
    # retrieve node configuration variables from param server
    yaml_package_name = rospy.get_param('~yaml_package_name', 'object_spawner')
    yaml_relative_path = rospy.get_param('~yaml_relative_path', '/config/models.yaml')
    random_order = rospy.get_param('~random_order', 'false')
    time_interval = rospy.get_param('~time_interval', 1.0)
    # parse yaml file to dictionary of Model objects
    m = parse_yaml(yaml_package_name,yaml_relative_path) # create dict called 'm'
   
    if random_order == True:
        ## spawn a random model parsed from yaml file
        try:    
            for key in random.sample(m.keys(), len(m)):
                spawn_model(m[key])
                # remove item form dict
                del m[key]
                if time_interval > 0:
                    # sleep for duration (seconds, nsecs)
                    d = rospy.Duration(time_interval)
                    rospy.sleep(d)
            # to silence "sys.excepthook is missing" error
            sys.stdout.flush() 
        except:
            pass
    else:
        ## spawn all models parsed from yaml file iterating through the dict (unordered sequence, as they were stored)
        for key in m:
            spawn_model(m[key])
            if time_interval > 0:
                # sleep for duration (seconds, nsecs)
                d = rospy.Duration(time_interval)
                rospy.sleep(d)
