// SPDX-License-Identifier: AGPL-3.0-or-later
// Run through desktop-ui.cjs against a fresh isolated Qt session.
const fs = require('node:fs');
const path = require('node:path');
module.exports = async ({page,expect,session}) => {
  if(session.mode !== 'isolated') throw Error('Isolated session required');
  const out=path.join(path.dirname(session.profile),'evidence');
  const nav=page.getByRole('navigation',{name:'Main navigation'});
  await nav.getByRole('button',{name:'Cloud',exact:true}).click();
  await expect(page.getByRole('button',{name:'Open Cloud folder',exact:true})).toBeVisible();
  await page.screenshot({path:path.join(out,'cloud.png')});
  await page.getByRole('button',{name:'Cloud settings',exact:true}).click();
  await expect(page.getByRole('tab',{name:'Connections',exact:true})).toHaveAttribute('aria-selected','true');
  await expect(page.getByRole('heading',{name:'Cloud folders',exact:true})).toBeVisible();
  await page.getByLabel('Cloud folder',{exact:true}).fill(path.join(session.profile,'Synthetic Cloud'));
  await page.getByRole('button',{name:'Save folder',exact:true}).click();
  await expect(page.getByText('Cloud folder saved.',{exact:true})).toBeVisible();
  expect(JSON.parse(fs.readFileSync(path.join(session.profile,'settings.json'),'utf8')).cloud.path).toBe(path.join(session.profile,'Synthetic Cloud'));
  await page.screenshot({path:path.join(out,'cloud-settings.png')});
  // Synthetic activity in this disposable profile, read through the real
  // native insights handler. No phone messages or usage-sharing consent.
  const {DatabaseSync}=require('node:sqlite');
  const database=new DatabaseSync(path.join(session.profile,'workspace.sqlite3'));
  try {
    const insert=database.prepare('INSERT INTO records(kind,id,data) VALUES(?,?,?) ON CONFLICT(kind,id) DO UPDATE SET data=excluded.data');
    [0,1,4,2,0,3,5].forEach((count,index)=>{
      const date=new Date();date.setUTCDate(date.getUTCDate()-6+index);
      const id=date.toISOString().slice(0,10);
      insert.run('insight_day',id,JSON.stringify({id,features:{sms_send:count,screen_messages:1}}));
    });
  } finally { database.close(); }
  await page.reload();
  await nav.getByRole('button',{name:'Settings',exact:true}).click();
  await page.getByRole('tab',{name:'General',exact:true}).click();
  await page.getByRole('heading',{name:'Your week',exact:true}).scrollIntoViewIfNeeded();
  await expect(page.getByRole('heading',{name:'Your week',exact:true})).toBeVisible();
  expect(await page.getByRole('heading',{name:'Your week',exact:true}).evaluate(el=>el.closest('details'))).toBe(null);
  await expect(page.getByRole('list',{name:'Daily activity',exact:true}).getByRole('listitem')).toHaveCount(7);
  await expect(page.getByText('Actions',{exact:true}).locator('..').getByRole('definition')).toHaveText('15');
  await page.screenshot({path:path.join(out,'weekly-summary.png')});
  await page.getByRole('button',{name:'Turn off Your week',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Your week',exact:true})).toHaveCount(0);
  const cleared=new DatabaseSync(path.join(session.profile,'workspace.sqlite3'));
  try { expect(cleared.prepare("SELECT COUNT(*) AS count FROM records WHERE kind='insight_day'").get().count).toBe(0); }
  finally { cleared.close(); }
  await page.getByRole('button',{name:'Turn on Your week',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Your week',exact:true})).toBeVisible();
  fs.writeFileSync(path.join(out,'layout-results.json'),JSON.stringify({passed:true,nativeQt:true,cloudSettingsSave:true,weeklySummaryVisible:true,weeklySummaryToggle:true,sevenDayChart:true,localCountsDeleted:true,syntheticActivity:true,liveAccounts:false},null,2));
};
