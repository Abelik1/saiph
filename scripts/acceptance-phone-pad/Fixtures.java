// SPDX-License-Identifier: AGPL-3.0-or-later
package ie.orion.acceptance.pad;

import android.content.*;
import android.database.*;
import android.net.Uri;
import android.os.*;
import android.provider.OpenableColumns;
import java.io.*;
import org.json.JSONObject;

public class Fixtures extends ContentProvider {
    @Override public boolean onCreate() { return true; }
    void fixtureReader(Uri uri) {
        int uid=Binder.getCallingUid();
        boolean granted=uid==android.os.Process.myUid() || getContext().checkUriPermission(uri,Binder.getCallingPid(),uid,Intent.FLAG_GRANT_READ_URI_PERMISSION)==android.content.pm.PackageManager.PERMISSION_GRANTED;
        Pad.prefs(getContext()).edit().putInt("last_fixture_reader_uid",uid).putBoolean("last_fixture_reader_explicit_grant",granted).apply();
        // This exported, read-only provider contains ONLY generated synthetic
        // fixtures. Public provider access need not carry an explicit URI grant.
        // Control/status calls below remain shell-only. Pad.file rejects paths.
    }
    @Override public Bundle call(String method,String arg,Bundle extras) {
        if(Binder.getCallingUid()!=2000 && Binder.getCallingUid()!=android.os.Process.myUid())throw new SecurityException("Shell only");
        if("command".equals(method)) {
            if(Pad.current==null)throw new IllegalStateException("Open the pad first");
            try {
                JSONObject input=new JSONObject(arg);Intent intent=new Intent();
                java.util.Iterator<String> keys=input.keys();while(keys.hasNext()) { String key=keys.next();intent.putExtra(key,input.getString(key)); }
                new Handler(Looper.getMainLooper()).post(() -> Pad.current.perform(intent));
            } catch(org.json.JSONException e) { throw new IllegalArgumentException("Fixture command JSON required"); }
        } else if(!"status".equals(method))throw new IllegalArgumentException("status or command only");
        Bundle out=new Bundle();JSONObject obj=new JSONObject(Pad.prefs(getContext()).getAll());
        try { obj.put("active_notifications",((android.app.NotificationManager)getContext().getSystemService(Context.NOTIFICATION_SERVICE)).getActiveNotifications().length); }
        catch(Exception ignored) {}
        out.putString("result",obj.toString());return out;
    }
    @Override public ParcelFileDescriptor openFile(Uri uri,String mode) throws FileNotFoundException {
        Pad.prefs(getContext()).edit().putString("last_fixture_open_mode",mode).apply();
        fixtureReader(uri);if(!"r".equals(mode))throw new FileNotFoundException("Read only");
        try { return ParcelFileDescriptor.open(Pad.file(getContext(),uri.getLastPathSegment()),ParcelFileDescriptor.MODE_READ_ONLY); }
        catch(Exception e) { throw new FileNotFoundException("Unknown fixture"); }
    }
    @Override public Cursor query(Uri uri,String[] projection,String selection,String[] args,String order) {
        fixtureReader(uri);
        try { File f=Pad.file(getContext(),uri.getLastPathSegment());String[] cols=projection==null?new String[]{OpenableColumns.DISPLAY_NAME,OpenableColumns.SIZE}:projection;
            MatrixCursor c=new MatrixCursor(cols);Object[] row=new Object[cols.length];for(int i=0;i<cols.length;i++)row[i]=OpenableColumns.DISPLAY_NAME.equals(cols[i])?f.getName():OpenableColumns.SIZE.equals(cols[i])?f.length():null;c.addRow(row);return c;
        } catch(Exception e) { throw new IllegalArgumentException("Unknown fixture"); }
    }
    @Override public String getType(Uri uri) { return uri.toString().endsWith(".png")?"image/png":"text/plain"; }
    @Override public Uri insert(Uri u,ContentValues v) { throw new UnsupportedOperationException(); }
    @Override public int delete(Uri u,String s,String[] a) { throw new UnsupportedOperationException(); }
    @Override public int update(Uri u,ContentValues v,String s,String[] a) { throw new UnsupportedOperationException(); }
}
