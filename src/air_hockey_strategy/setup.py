from setuptools import setup

package_name = 'air_hockey_strategy'

setup(
    name=package_name,
    version='0.0.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Alex Lewandowski',
    maintainer_email='Alexlewandowski08@gmail.com',
    description='Air hockey strategy node',
    license='MIT',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'strategy_node = air_hockey_strategy.strategy_node:main',
        ],
    },
)
