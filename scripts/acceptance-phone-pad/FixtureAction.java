// SPDX-License-Identifier: AGPL-3.0-or-later
package ie.orion.acceptance.pad;

import android.content.*;
import android.os.Bundle;
import android.app.RemoteInput;

public class FixtureAction extends BroadcastReceiver {
    @Override public void onReceive(Context c,Intent i) {
        android.content.SharedPreferences p=Pad.prefs(c);
        if("mark".equals(i.getAction()))p.edit().putInt("mark_count",p.getInt("mark_count",0)+1).apply();
        if("reply".equals(i.getAction())) {
            Bundle b=RemoteInput.getResultsFromIntent(i);
            p.edit().putInt("reply_count",p.getInt("reply_count",0)+1).putBoolean("reply_match",b!=null && "ORION-FIXTURE-REPLY".contentEquals(b.getCharSequence("fixture_reply",""))).apply();
        }
    }
}
