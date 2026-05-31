cmake_minimum_required(VERSION 3.22.1)
project("mdcs_native")

# 设置C++标准
set(CMAKE_CXX_STANDARD 17)

# 查找Android NDK提供的库
find_library(log-lib log)
find_library(android-lib android)

# 如果集成MNN C++ API，可以在这里添加
# add_subdirectory(${MNN_ROOT} mnn)

# 创建native库（用于高性能计算或自定义算子）
add_library(
    mdcs_native
    SHARED
    inference_bridge.cpp
)

target_link_libraries(
    mdcs_native
    ${log-lib}
    ${android-lib}
)
