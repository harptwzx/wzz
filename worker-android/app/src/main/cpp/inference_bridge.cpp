#include <jni.h>
#include <android/log.h>

#define LOG_TAG "MDCS_Native"
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, LOG_TAG, __VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, LOG_TAG, __VA_ARGS__)

extern "C" {

/**
 * 高性能矩阵运算桥接（可选）
 * 当TFLite/MNN不满足需求时，可通过JNI调用自定义NEON优化算子
 */
JNIEXPORT void JNICALL
Java_com_compute_worker_inference_InferenceEngine_nativeRunLayer(
    JNIEnv* env,
    jobject thiz,
    jint layerIndex,
    jfloatArray input,
    jfloatArray output
) {
    // 获取输入数组
    jfloat* inputPtr = env->GetFloatArrayElements(input, nullptr);
    jfloat* outputPtr = env->GetFloatArrayElements(output, nullptr);

    jsize inputSize = env->GetArrayLength(input);
    jsize outputSize = env->GetArrayLength(output);

    LOGI("Native layer %d: input=%d, output=%d", layerIndex, inputSize, outputSize);

    // 这里可以插入NEON优化的矩阵乘法或自定义算子
    // 简化：直接拷贝（实际应执行推理）
    for (int i = 0; i < outputSize && i < inputSize; i++) {
        outputPtr[i] = inputPtr[i];
    }

    env->ReleaseFloatArrayElements(input, inputPtr, JNI_ABORT);
    env->ReleaseFloatArrayElements(output, outputPtr, 0);
}

/**
 * 内存池分配（大页支持）
 */
JNIEXPORT jlong JNICALL
Java_com_compute_worker_inference_InferenceEngine_00024MemoryPool_nativeAllocate(
    JNIEnv* env,
    jobject thiz,
    jint size
) {
    // 尝试使用大页内存分配（减少TLB miss）
    void* ptr = malloc(size);
    if (ptr) {
        LOGI("Native allocated %d bytes at %p", size, ptr);
    }
    return reinterpret_cast<jlong>(ptr);
}

}
