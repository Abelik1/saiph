package sefirah.worker;

interface IWorkerService {
    /** Stop watching and exit the process. */
    void destroy() = 16777114;

    void startWatching() = 1;

    void stopWatching() = 2;

    /** Increment inbound suppress count (one per app setPrimaryClip). */
    void suppressNextOutbound() = 3;

    /** Must match worker module versionCode — app replaces the process on mismatch. */
    int getVersion() = 4;
}
