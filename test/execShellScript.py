import subprocess

start_edna_command = '/home/mxcube19u1/mxcube/mxcubecore/edna_script.sh'
input_file = '/ramdisk/bl19u1/inhouse/zhangsan1/20240501/PROCESSED_DATA/N155H/EDNAInput_152.json'
results_file = '/ramdisk/bl19u1/inhouse/zhangsan1/20240501/PROCESSED_DATA/N155H/EDNAOutput_152.xml'
process_directory = '/ramdisk/bl19u1/inhouse/zhangsan1/20240501/PROCESSED_DATA/N155H/'
args = (start_edna_command, input_file, results_file, process_directory)
subprocess.call("%s %s %s %s" % args, shell=True)