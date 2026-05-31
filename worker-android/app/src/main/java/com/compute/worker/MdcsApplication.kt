package com.compute.worker

import android.app.Application
import timber.log.Timber

/**
 * MDCS Worker Application
 * 初始化日志、全局配置
 */
class MdcsApplication : Application() {

    override fun onCreate() {
        super.onCreate()

        // Initialize Timber logging
        if (BuildConfig.DEBUG) {
            Timber.plant(Timber.DebugTree())
        } else {
            Timber.plant(CrashReportingTree())
        }

        Timber.i("MDCS Worker Application initialized")
    }

    private class CrashReportingTree : Timber.Tree() {
        override fun log(priority: Int, tag: String?, message: String, t: Throwable?) {
            // In production, send to crash analytics
        }
    }
}
