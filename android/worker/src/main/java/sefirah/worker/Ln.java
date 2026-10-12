package sefirah.worker;

import android.util.Log;

/** One logcat tag for the whole worker, same idea as scrcpy's {@code Ln}. */
final class Ln {
    private static final String TAG = "sefirah_worker";

    private Ln() {
    }

    static void i(String msg) {
        Log.i(TAG, msg);
    }

    static void w(String msg) {
        Log.w(TAG, msg);
    }

    static void w(String msg, Throwable t) {
        Log.w(TAG, msg, t);
    }

    static void e(String msg) {
        Log.e(TAG, msg);
    }

    static void e(String msg, Throwable t) {
        Log.e(TAG, msg, t);
    }
}
