# IMPORTANT:
#   Make sure you run Blender as administrator before running this script.
#   If you don't, libraries will be installed in AppData/Local directory and
#   will NOT be recognized by Blender.
# 
# NOTE:
#   This may take a few mins & will freeze Blender.
#   You should enable Window > Toggle the System Console to watch the update progress.
#
#   I'm not entirely sure, but running Blender as admin seems to disable some features.
#   You may want to restart and launch normally after installing these dependencies.

import subprocess
import sys

def install_packages(package_list):
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", *package_list])
        print(f"Successfully installed all packages: {', '.join(package_list)}")
    except subprocess.CalledProcessError as e:
        print(f"An error occurred during installation. Error: {e}")

if __name__ == "__main__":
    packages_to_install = ["scipy", "scikit-learn", "pymeshlab", "PyMaxFlow"]
    install_packages(packages_to_install)
