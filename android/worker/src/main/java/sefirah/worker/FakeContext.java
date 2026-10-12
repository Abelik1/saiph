package sefirah.worker;

import android.annotation.SuppressLint;
import android.content.AttributionSource;
import android.content.ContentResolver;
import android.content.Context;
import android.content.ContextWrapper;
import android.content.IContentProvider;
import android.os.Build;
import android.os.Process;
import androidx.annotation.NonNull;
import androidx.annotation.RequiresApi;
import java.lang.reflect.Field;

/**
 * From scrcpy <a href="https://github.com/Genymobile/scrcpy/blob/master/server/src/main/java/com/genymobile/scrcpy/FakeContext.java">{@code FakeContext}</a>
 */
final class FakeContext extends ContextWrapper {

    static final String PACKAGE_NAME = "com.android.shell";
    /** Like {@link Process#ROOT_UID}, but before API 29. */
    static final int ROOT_UID = 0;

    private static final FakeContext INSTANCE = new FakeContext();

    private final ContentResolver contentResolver = new ContentResolver(this) {
        @SuppressWarnings({"unused", "ProtectedMemberInFinalClass"})
        // @Override (but super-class method not visible)
        protected IContentProvider acquireProvider(Context c, String name) {
            return ActivityManagers.getContentProviderExternal(name);
        }

        @SuppressWarnings("unused")
        // @Override (but super-class method not visible)
        public boolean releaseProvider(IContentProvider icp) {
            return false;
        }

        @SuppressWarnings({"unused", "ProtectedMemberInFinalClass"})
        // @Override (but super-class method not visible)
        protected IContentProvider acquireUnstableProvider(Context c, String name) {
            return ActivityManagers.getContentProviderExternal(name);
        }

        @SuppressWarnings("unused")
        // @Override (but super-class method not visible)
        public boolean releaseUnstableProvider(IContentProvider icp) {
            return false;
        }

        @SuppressWarnings("unused")
        // @Override (but super-class method not visible)
        public void unstableProviderDied(IContentProvider icp) {
            // ignore
        }
    };

    static FakeContext get() {
        return INSTANCE;
    }

    private FakeContext() {
        super(systemContext());
    }

    private static Context systemContext() {
        try {
            Class<?> activityThreadClass = Class.forName("android.app.ActivityThread");
            Object thread = activityThreadClass.getMethod("systemMain").invoke(null);
            Object context = activityThreadClass.getMethod("getSystemContext").invoke(thread);
            if (!(context instanceof Context)) {
                throw new IllegalStateException("ActivityThread.getSystemContext() returned null");
            }
            return (Context) context;
        } catch (ReflectiveOperationException e) {
            throw new RuntimeException("Failed to create system context", e);
        }
    }

    @Override
    public String getPackageName() {
        return PACKAGE_NAME;
    }

    @NonNull
    @Override
    public String getOpPackageName() {
        return PACKAGE_NAME;
    }

    @NonNull
    @RequiresApi(Build.VERSION_CODES.S)
    @Override
    public AttributionSource getAttributionSource() {
        return new AttributionSource.Builder(Process.SHELL_UID)
                .setPackageName(PACKAGE_NAME)
                .build();
    }

    // @Override to be added on SDK upgrade for Android 14
    @SuppressWarnings("unused")
    public int getDeviceId() {
        return 0;
    }

    @Override
    public Context getApplicationContext() {
        return this;
    }

    @Override
    public Context createPackageContext(String packageName, int flags) {
        return this;
    }

    @Override
    public ContentResolver getContentResolver() {
        return contentResolver;
    }

    @SuppressLint("SoonBlockedPrivateApi")
    @Override
    public Object getSystemService(String name) {
        Object service = super.getSystemService(name);
        if (service == null) {
            return null;
        }

        // "semclipboard" is a Samsung-internal service
        if (Context.CLIPBOARD_SERVICE.equals(name)
                || "semclipboard".equals(name)
                || Context.ACTIVITY_SERVICE.equals(name)) {
            try {
                Field field = service.getClass().getDeclaredField("mContext");
                field.setAccessible(true);
                field.set(service, this);
            } catch (ReflectiveOperationException e) {
                throw new RuntimeException(e);
            }
        }

        return service;
    }
}
