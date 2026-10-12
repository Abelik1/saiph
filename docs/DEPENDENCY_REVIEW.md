# Android dependency review

Reviewed 2026-10-11 against source base `98a206f`, the GitHub Maven alert list,
and resolved Gradle graphs with JDK 22, Firebase off, independent builds and push
off. This is dependency triage, not an independent security review or physical
Android acceptance.

## Result and scope

The snapshot contains **56 open Maven alerts: 8 critical, 20 high, 26 medium and
2 low**. The targeted version floors address **55 alerts** in the resolved graphs.
**One medium Kotlin build-tool advisory remains**, with its affected KAPT path
explicitly blocked. This does not claim that GitHub has closed the alerts; the
main-branch dependency submission must run after merging and the alert list must
then be checked again. New advisories can change this result.

The app's debug, beta and release runtime graphs contained Bouncy Castle 1.79,
MINA 2.2.4 and Commons Lang 3.17.0. These become 1.85, 2.2.8 and 3.18.0 respectively.
Bouncy Castle's provider, PKIX and utility modules remain aligned. Existing package
names, signing, pairing, device keys and invitation formats are unchanged.

The 41 Netty alerts concern **host Android Unified Test Platform tooling**, reached
through its emulator-control and core configurations with gRPC. Netty was absent
from the checked APK runtime graphs. The tool configurations previously selected
4.1.93.Final / 4.1.110.Final and now select 4.1.137.Final across their mutually
dependent transport modules. The 4.1 family is retained; this does not migrate
the app's networking stack to Netty or upgrade to Netty 4.2.

Other affected plugin/lint dependencies become jose4j 0.9.6, JDOM 2.0.6.1, Commons
Lang 3.18.0, HttpClient 4.5.14 and Bouncy Castle 1.85. HttpClient was already fixed
in the main plugin classpath, but **not** in the lint classpath, which selected
4.5.6. Merely inspecting the application runtime or top-level buildscript would
have missed that exposure.

`android/gradle/security-dependencies.gradle` supplies minimum constraints before
both project and plugin classpaths resolve, including the convention-plugin
included build. Constraints do not introduce libraries or downgrade a future
upstream version. The catalog also declares patched runtime versions directly. Bouncy Castle 1.85
adds the same `META-INF/LICENSE.md` resource in three modules; APK packaging
merges that path to retain the license text while avoiding duplicate-resource
errors.

## Remaining Kotlin advisory

Alert #51, [CVE-2026-53914](https://github.com/advisories/GHSA-r937-wjx7-w2jp), covers
Kotlin Gradle Plugin versions before 2.4.20-Beta1. The resolved main plugin remains
2.3.0 and the Gradle Kotlin DSL convention-plugin build uses 2.4.0. Both are below
the patched range and are **not recorded as fixed**.

The [upstream fix](https://github.com/JetBrains/kotlin/commit/bf51df665b458fda7c3eaf436c4d88dc119d7ec6)
restricts Java deserialization in **KAPT incremental annotation-processing caches**.
This repository uses KSP and applies no KAPT plugin. The shared settings script
fails configuration if `org.jetbrains.kotlin.kapt` or its legacy `kotlin-kapt`
alias is enabled in either build.
Keep Gradle/Kotlin caches isolated and do not import caches from untrusted builds.
The guard reduces exposure; it is not a patched Kotlin version or a vulnerability
waiver. Validate a compatible AGP, KSP, Compose compiler and Kotlin DSL toolchain
upgrade before removing the guard. Simply changing the catalog Kotlin version
would still leave Gradle's embedded Kotlin DSL plugin dependency to address.

## Reproduce the graph check

From `android/`, with the documented JDK/SDK and an isolated `GRADLE_USER_HOME`:

```powershell
./gradlew.bat verifyDependencySecurity :build-logic:verifyDependencySecurity --init-script ../scripts/android/dependency-review.init.gradle -PorionFirebase=false -PorionIndependent=true -PorionPush=false -PorionVersionCode=1 --no-configuration-cache
```

The verifier checks every resolvable project and plugin configuration in both
builds, fails on unresolved modules or a selected version below a security floor,
and rejects same-base prereleases (including RC, Beta and SNAPSHOT) while
recognizing Netty `.Final` as stable. Comparator regression cases run as a
prerequisite. The verifier records sorted module/version/configuration entries in each build's
`build/reports/dependency-security.json`. It reports Kotlin versions without
claiming that the advisory is patched. The Android workflow runs this check before
its debug/beta assemblies, debug JVM tests and debug/beta lint.

No Firebase configuration, credentials, signing keys, phone, owner Hub, uploads or
service operations are needed. Resolving UTP dependencies does not start an
emulator or run tests on a device.

## Validation

Local checks passed with Firebase and push off, using JDK 22 and isolated caches:

- The maintained verifier checked 597 Android and 2 included-build resolved
  module/configuration entries, with zero unresolved or below-floor failures.
- Fourteen version-comparator regression cases passed in each build, including
  stable/equal/newer versions, older versions, same-base RC/Beta/alpha/SNAPSHOT
  and unknown qualifiers, plus Netty `.Final` and `.Final-SNAPSHOT`.
- A synthetic JVM configuration without KAPT passed. Applying either
  `org.jetbrains.kotlin.kapt` or `kotlin-kapt` failed with the intended guard.
- Debug and beta APK assemblies passed. Both APKs retained the Bouncy Castle
  license text from all three modules after fixing the initial packaging collision.
- App/network/restic debug JVM suites: **126 passed, 2 skipped, 0 failures/errors**.
- Debug and beta lint: **0 errors, 154 warnings** in each variant.

CI results are recorded in the pull request. Release dependencies were resolved,
but a minified release APK is not claimed as device-accepted. UTP/emulator
execution and physical Android pairing, upgrades and background recovery remain
separate tests. No private Firebase configuration, signing keys or device/Hub
access were used.

## Alert-by-alert disposition

Every alert in the snapshot uses manifest `android/settings.gradle.kts`. Scope
below comes from actual resolved configurations, not that manifest label. Fix
versions are minimums verified against Maven Central metadata and the listed
advisories; severity is the GitHub snapshot's severity.

| Alert | Package | Severity | Advisory | Baseline | Selected floor / disposition | Scope |
| --- | --- | --- | --- | --- | --- | --- |
| #1 | `org.apache.httpcomponents:httpclient` | medium | [CVE-2020-13956](https://github.com/advisories/GHSA-7r82-7xv7-xcpj) | 4.5.6 / 4.5.14 | 4.5.14 | lint / plugin tooling |
| #2 | `io.netty:netty-handler` | medium | [CVE-2023-34462](https://github.com/advisories/GHSA-6mjq-h674-j845) | 4.1.93.Final / 4.1.110.Final | 4.1.137.Final | UTP host test tooling |
| #3 | `io.netty:netty-codec-http2` | high | [GHSA-xpw8-rcwv-8f8p](https://github.com/advisories/GHSA-xpw8-rcwv-8f8p) | 4.1.93.Final / 4.1.110.Final | 4.1.137.Final | UTP host test tooling |
| #4 | `io.netty:netty-codec-http` | medium | [CVE-2024-29025](https://github.com/advisories/GHSA-5jpm-x58v-624v) | 4.1.93.Final / 4.1.110.Final | 4.1.137.Final | UTP host test tooling |
| #5 | `io.netty:netty-handler` | high | [CVE-2025-24970](https://github.com/advisories/GHSA-4g8c-wm8x-jfhw) | 4.1.93.Final / 4.1.110.Final | 4.1.137.Final | UTP host test tooling |
| #6 | `io.netty:netty-common` | medium | [CVE-2024-47535](https://github.com/advisories/GHSA-xq3w-v528-46rv) | 4.1.93.Final / 4.1.110.Final | 4.1.137.Final | UTP host test tooling |
| #7 | `io.netty:netty-common` | medium | [CVE-2025-25193](https://github.com/advisories/GHSA-389x-839f-4rhx) | 4.1.93.Final / 4.1.110.Final | 4.1.137.Final | UTP host test tooling |
| #8 | `org.apache.commons:commons-lang3` | medium | [CVE-2025-48924](https://github.com/advisories/GHSA-j288-q9x7-2f5v) | 3.17.0 / 3.16.0 | 3.18.0 | APK + plugin/lint tooling |
| #9 | `io.netty:netty-codec-http2` | high | [CVE-2025-55163](https://github.com/advisories/GHSA-prj3-ccx8-p6x4) | 4.1.93.Final / 4.1.110.Final | 4.1.137.Final | UTP host test tooling |
| #10 | `io.netty:netty-codec` | medium | [CVE-2025-58057](https://github.com/advisories/GHSA-3p8m-j85q-pgmj) | 4.1.93.Final / 4.1.110.Final | 4.1.137.Final | UTP host test tooling |
| #11 | `io.netty:netty-codec-http` | low | [CVE-2025-58056](https://github.com/advisories/GHSA-fghv-69vj-qj49) | 4.1.93.Final / 4.1.110.Final | 4.1.137.Final | UTP host test tooling |
| #12 | `org.jdom:jdom2` | high | [CVE-2021-33813](https://github.com/advisories/GHSA-2363-cqg2-863c) | 2.0.6 | 2.0.6.1 | build plugin |
| #13 | `io.netty:netty-codec-http` | medium | [CVE-2025-67735](https://github.com/advisories/GHSA-84h7-rjj3-6jx4) | 4.1.93.Final / 4.1.110.Final | 4.1.137.Final | UTP host test tooling |
| #14 | `org.bitbucket.b_c:jose4j` | high | [CVE-2024-29371](https://github.com/advisories/GHSA-3677-xxcr-wjqv) | 0.9.5 | 0.9.6 | build plugin |
| #15 | `io.netty:netty-codec-http` | high | [CVE-2026-33870](https://github.com/advisories/GHSA-pwqr-wmgm-9rr8) | 4.1.93.Final / 4.1.110.Final | 4.1.137.Final | UTP host test tooling |
| #16 | `io.netty:netty-codec-http2` | high | [CVE-2026-33871](https://github.com/advisories/GHSA-w9fj-cfpg-grvv) | 4.1.93.Final / 4.1.110.Final | 4.1.137.Final | UTP host test tooling |
| #17 | `org.bouncycastle:bcpkix-jdk18on` | medium | [CVE-2026-5588](https://github.com/advisories/GHSA-wg6q-6289-32hp) | 1.79 | 1.85 | APK + plugin/lint tooling |
| #18 | `org.bouncycastle:bcprov-jdk18on` | medium | [CVE-2026-0636](https://github.com/advisories/GHSA-c3fc-8qff-9hwx) | 1.79 | 1.85 | APK + plugin/lint tooling |
| #19 | `io.netty:netty-codec-http` | medium | [CVE-2026-41417](https://github.com/advisories/GHSA-v8h7-rr48-vmmv) | 4.1.93.Final / 4.1.110.Final | 4.1.137.Final | UTP host test tooling |
| #20 | `org.apache.mina:mina-core` | critical | [CVE-2026-41409](https://github.com/advisories/GHSA-f2wh-grmh-r6jm) | 2.2.4 | 2.2.8 | APK |
| #21 | `io.netty:netty-handler-proxy` | low | [CVE-2026-42578](https://github.com/advisories/GHSA-45q3-82m4-75jr) | 4.1.93.Final / 4.1.110.Final | 4.1.137.Final | UTP host test tooling |
| #22 | `io.netty:netty-codec-http` | medium | [CVE-2026-42580](https://github.com/advisories/GHSA-m4cv-j2px-7723) | 4.1.93.Final / 4.1.110.Final | 4.1.137.Final | UTP host test tooling |
| #23 | `io.netty:netty-codec-http` | medium | [CVE-2026-42581](https://github.com/advisories/GHSA-xxqh-mfjm-7mv9) | 4.1.93.Final / 4.1.110.Final | 4.1.137.Final | UTP host test tooling |
| #24 | `io.netty:netty-codec` | high | [CVE-2026-42583](https://github.com/advisories/GHSA-mj4r-2hfc-f8p6) | 4.1.93.Final / 4.1.110.Final | 4.1.137.Final | UTP host test tooling |
| #25 | `io.netty:netty-codec-http` | high | [CVE-2026-42584](https://github.com/advisories/GHSA-57rv-r2g8-2cj3) | 4.1.93.Final / 4.1.110.Final | 4.1.137.Final | UTP host test tooling |
| #26 | `io.netty:netty-codec-http` | medium | [CVE-2026-42585](https://github.com/advisories/GHSA-38f8-5428-x5cv) | 4.1.93.Final / 4.1.110.Final | 4.1.137.Final | UTP host test tooling |
| #27 | `io.netty:netty-codec-http` | high | [CVE-2026-42587](https://github.com/advisories/GHSA-f6hv-jmp6-3vwv) | 4.1.93.Final / 4.1.110.Final | 4.1.137.Final | UTP host test tooling |
| #28 | `io.netty:netty-codec-http2` | high | [CVE-2026-42587](https://github.com/advisories/GHSA-f6hv-jmp6-3vwv) | 4.1.93.Final / 4.1.110.Final | 4.1.137.Final | UTP host test tooling |
| #29 | `org.apache.mina:mina-core` | critical | [CVE-2026-42778](https://github.com/advisories/GHSA-995c-6rp3-4m4x) | 2.2.4 | 2.2.8 | APK |
| #30 | `org.apache.mina:mina-core` | critical | [CVE-2026-42779](https://github.com/advisories/GHSA-vf5j-865m-mq7c) | 2.2.4 | 2.2.8 | APK |
| #31 | `org.apache.mina:mina-core` | critical | [CVE-2026-41635](https://github.com/advisories/GHSA-8297-v2rf-2p32) | 2.2.4 | 2.2.8 | APK |
| #32 | `io.netty:netty-handler` | high | [CVE-2026-44249](https://github.com/advisories/GHSA-3qp7-7mw8-wx86) | 4.1.93.Final / 4.1.110.Final | 4.1.137.Final | UTP host test tooling |
| #33 | `io.netty:netty-handler` | high | [CVE-2026-45416](https://github.com/advisories/GHSA-x4gw-5cx5-pgmh) | 4.1.93.Final / 4.1.110.Final | 4.1.137.Final | UTP host test tooling |
| #34 | `io.netty:netty-codec-http2` | medium | [CVE-2026-47244](https://github.com/advisories/GHSA-5x3r-wrvg-rp6q) | 4.1.93.Final / 4.1.110.Final | 4.1.137.Final | UTP host test tooling |
| #35 | `io.netty:netty-codec-http2` | medium | [CVE-2026-48043](https://github.com/advisories/GHSA-c2gf-v879-257j) | 4.1.93.Final / 4.1.110.Final | 4.1.137.Final | UTP host test tooling |
| #36 | `io.netty:netty-handler` | high | [CVE-2026-50010](https://github.com/advisories/GHSA-c653-97m9-rcg9) | 4.1.93.Final / 4.1.110.Final | 4.1.137.Final | UTP host test tooling |
| #37 | `io.netty:netty-codec-http` | medium | [CVE-2026-50020](https://github.com/advisories/GHSA-hvcg-qmg6-jm4c) | 4.1.93.Final / 4.1.110.Final | 4.1.137.Final | UTP host test tooling |
| #38 | `io.netty:netty-codec-http2` | medium | [CVE-2026-50560](https://github.com/advisories/GHSA-563q-j3cm-6jxm) | 4.1.93.Final / 4.1.110.Final | 4.1.137.Final | UTP host test tooling |
| #39 | `org.bouncycastle:bcprov-jdk18on` | critical | [CVE-2025-14813](https://github.com/advisories/GHSA-574f-3g2m-x479) | 1.79 | 1.85 | APK + plugin/lint tooling |
| #40 | `org.apache.mina:mina-core` | critical | [CVE-2026-47065](https://github.com/advisories/GHSA-v3pr-hxpr-mfm8) | 2.2.4 | 2.2.8 | APK |
| #41 | `io.netty:netty-codec-http` | high | [CVE-2026-55831](https://github.com/advisories/GHSA-6jqx-86gh-f27w) | 4.1.93.Final / 4.1.110.Final | 4.1.137.Final | UTP host test tooling |
| #42 | `io.netty:netty-codec-http` | high | [CVE-2026-55833](https://github.com/advisories/GHSA-mvh2-crg5-v77c) | 4.1.93.Final / 4.1.110.Final | 4.1.137.Final | UTP host test tooling |
| #43 | `io.netty:netty-codec-http` | high | [CVE-2026-56745](https://github.com/advisories/GHSA-jppx-w49h-x2qq) | 4.1.93.Final / 4.1.110.Final | 4.1.137.Final | UTP host test tooling |
| #44 | `io.netty:netty-codec-http` | medium | [CVE-2026-56746](https://github.com/advisories/GHSA-6cqp-g7gg-8hr5) | 4.1.93.Final / 4.1.110.Final | 4.1.137.Final | UTP host test tooling |
| #45 | `io.netty:netty-codec-http` | medium | [CVE-2026-59898](https://github.com/advisories/GHSA-4mp9-239f-g9hg) | 4.1.93.Final / 4.1.110.Final | 4.1.137.Final | UTP host test tooling |
| #46 | `io.netty:netty-codec-http` | medium | [CVE-2026-59899](https://github.com/advisories/GHSA-q4f6-jm68-57ww) | 4.1.93.Final / 4.1.110.Final | 4.1.137.Final | UTP host test tooling |
| #47 | `io.netty:netty-codec-http2` | medium | [CVE-2026-59900](https://github.com/advisories/GHSA-c69g-56f8-xwqj) | 4.1.93.Final / 4.1.110.Final | 4.1.137.Final | UTP host test tooling |
| #48 | `io.netty:netty-codec` | high | [CVE-2026-59901](https://github.com/advisories/GHSA-558v-64gr-wgg4) | 4.1.93.Final / 4.1.110.Final | 4.1.137.Final | UTP host test tooling |
| #49 | `io.netty:netty-codec-http` | medium | [CVE-2026-59921](https://github.com/advisories/GHSA-gcjf-9mgh-3p7g) | 4.1.93.Final / 4.1.110.Final | 4.1.137.Final | UTP host test tooling |
| #50 | `io.netty:netty-codec-http2` | high | [CVE-2026-56819](https://github.com/advisories/GHSA-93wv-jw9v-4972) | 4.1.93.Final / 4.1.110.Final | 4.1.137.Final | UTP host test tooling |
| #51 | `org.jetbrains.kotlin:kotlin-gradle-plugin` | medium | [CVE-2026-53914](https://github.com/advisories/GHSA-r937-wjx7-w2jp) | 2.3.0 / 2.4.0 | retained; KAPT blocked | build plugin / included build |
| #52 | `io.netty:netty-codec-http` | medium | [CVE-2026-59903](https://github.com/advisories/GHSA-8c42-7qj2-3j46) | 4.1.93.Final / 4.1.110.Final | 4.1.137.Final | UTP host test tooling |
| #53 | `io.netty:netty-handler` | medium | [CVE-2026-75596](https://github.com/advisories/GHSA-fccg-mwvh-qqg4) | 4.1.93.Final / 4.1.110.Final | 4.1.137.Final | UTP host test tooling |
| #54 | `io.netty:netty-handler` | critical | [CVE-2026-75595](https://github.com/advisories/GHSA-c4c3-7fpv-j4q5) | 4.1.93.Final / 4.1.110.Final | 4.1.137.Final | UTP host test tooling |
| #55 | `org.bouncycastle:bcprov-jdk18on` | critical | [CVE-2026-8763](https://github.com/advisories/GHSA-9pwp-9qqc-pr26) | 1.79 | 1.85 | APK + plugin/lint tooling |
| #56 | `org.bouncycastle:bcprov-jdk18on` | high | [CVE-2026-13506](https://github.com/advisories/GHSA-qp49-qgx5-5m26) | 1.79 | 1.85 | APK + plugin/lint tooling |
