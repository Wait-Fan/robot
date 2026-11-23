data_files=[
    ('share/ament_index/resource_index/packages',
        ['resource/' + package_name]),
    ('share/' + package_name, ['package.xml']),
    # 新增这两行！
    ('share/' + package_name + '/launch', glob('launch/*.launch.py')),
    ('share/' + package_name + '/urdf', glob('urdf/*.urdf')),
],
