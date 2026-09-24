import os
from glob import glob

from setuptools import setup

package_name = 'air_hockey_sim'

setup(
    name=package_name,
    version='0.0.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.launch.py')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Alex Lewandowski',
    maintainer_email='Alexlewandowski08@gmail.com',
    description='2D air hockey simulator node',
    license='MIT',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'sim_node = air_hockey_sim.sim_node:main',
        ],
    },
)
