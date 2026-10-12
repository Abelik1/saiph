package sefirah.worker;

import android.content.IContentProvider;

import rikka.hidden.compat.ActivityManagerApis;

/** Thin AM helpers used by {@link FakeContext} and {@link ContentProviders}. */
final class ActivityManagers {
    private ActivityManagers() {
    }

    static IContentProvider getContentProviderExternal(String name) {
        try {
            // Passing a Binder token to system_server always yields a new BinderProxy.
            // getContentProviderExternal / removeContentProviderExternal key a HashMap by
            // that IBinder, and BinderProxy does not implement hashCode, so remove never
            // matches. Null token: name + refcount
            return ActivityManagerApis.getContentProviderExternal(name, FakeContext.ROOT_UID, null, null);
        } catch (Exception e) {
            Ln.e("getContentProviderExternal failed for " + name, e);
            return null;
        }
    }

    static void removeContentProviderExternal(String name) {
        try {
            ActivityManagerApis.removeContentProviderExternal(name, null);
        } catch (Exception e) {
            Ln.w("removeContentProviderExternal failed for " + name, e);
        }
    }
}
