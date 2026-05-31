# ProGuard rules for MDCS Worker
-keep class com.compute.worker.** { *; }
-keep class com.alibaba.mnn.** { *; }
-keep class org.tensorflow.lite.** { *; }
-dontwarn org.xerial.snappy.**
