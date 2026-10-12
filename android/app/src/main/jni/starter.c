#include "misc.h"

#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define perrorf(...) fprintf(stderr, __VA_ARGS__)

#define EXIT_FATAL_SET_CLASSPATH 3
#define EXIT_FATAL_FORK 4
#define EXIT_FATAL_APP_PROCESS 5
#define EXIT_FATAL_UID 6
#define EXIT_FATAL_PM_PATH 7
#define EXIT_FATAL_KILL 9

#define SERVER_NAME "sefirah_worker"
#define SERVER_CLASS_PATH "sefirah.worker.WorkerService"

static void run_server(const char *apk_path, const char *main_class, const char *process_name) {
    if (setenv("CLASSPATH", apk_path, 1) != 0) {
        perrorf("fatal: can't set CLASSPATH\n");
        exit(EXIT_FATAL_SET_CLASSPATH);
    }

    char class_path[PATH_MAX];
    snprintf(class_path, sizeof(class_path), "-Djava.class.path=%s", apk_path);

    char nice_name[256];
    snprintf(nice_name, sizeof(nice_name), "--nice-name=%s", process_name);

    char *args[] = {
            "/system/bin/app_process",
            class_path,
            "/system/bin",
            nice_name,
            (char *) main_class,
            NULL,
    };

    execvp(args[0], args);
    perrorf("fatal: exec app_process failed\n");
    exit(EXIT_FATAL_APP_PROCESS);
}

static void start_server(const char *path, const char *main_class, const char *process_name) {
    int fds[2];
    if (pipe(fds) < 0) {
        perrorf("fatal: can't create pipe\n");
        exit(EXIT_FATAL_FORK);
    }

    pid_t pid = fork();
    switch (pid) {
        case -1: {
            perrorf("fatal: can't fork\n");
            exit(EXIT_FATAL_FORK);
        }
        case 0: {
            close(fds[0]);
            setsid();
            chdir("/");
            int fd = open("/dev/null", O_RDWR);
            if (fd != -1) {
                dup2(fd, STDIN_FILENO);
                dup2(fd, STDOUT_FILENO);
                dup2(fd, STDERR_FILENO);
                if (fd > 2)
                    close(fd);
            }
            char ready = 1;
            write(fds[1], &ready, 1);
            close(fds[1]);
            run_server(path, main_class, process_name);
        }
        default: {
            close(fds[1]);
            char ready;
            read(fds[0], &ready, 1);
            close(fds[0]);
            exit(EXIT_SUCCESS);
        }
    }
}

static void kill_old_server_cb(pid_t pid) {
    if (pid == getpid())
        return;

    char name[1024];
    if (get_proc_name(pid, name, sizeof(name)) != 0)
        return;
    if (strcmp(name, SERVER_NAME) != 0)
        return;

    if (kill(pid, SIGKILL) == 0)
        printf("info: killed %d (%s)\n", pid, name);
    else if (errno == EPERM) {
        perrorf("fatal: can't kill %d, stop the existing worker first\n", pid);
        exit(EXIT_FATAL_KILL);
    } else {
        printf("warn: failed to kill %d (%s)\n", pid, name);
    }
}

int main(int argc, char *argv[]) {
    char apk_path[PATH_MAX] = {0};
    for (int i = 1; i < argc; ++i) {
        if (strncmp(argv[i], "--apk=", 6) == 0)
            strncpy(apk_path, argv[i] + 6, sizeof(apk_path) - 1);
    }

    uid_t uid = getuid();
    if (uid != 0 && uid != 2000) {
        perrorf("fatal: run worker starter from root or adb shell (uid=%d)\n", uid);
        exit(EXIT_FATAL_UID);
    }

    foreach_proc(kill_old_server_cb);

    if (apk_path[0] == '\0') {
        char buf[PATH_MAX];
        ssize_t len = readlink("/proc/self/exe", buf, sizeof(buf) - 1);
        if (len != -1) {
            buf[len] = '\0';
            char *lib_pos = strstr(buf, "/lib/");
            if (lib_pos) {
                size_t prefix_len = (size_t) (lib_pos - buf);
                if (prefix_len + strlen("/base.apk") < sizeof(apk_path)) {
                    memcpy(apk_path, buf, prefix_len);
                    apk_path[prefix_len] = '\0';
                    strncat(apk_path, "/base.apk", sizeof(apk_path) - prefix_len - 1);
                }
            }
        }
    }

    if (apk_path[0] == '\0' || access(apk_path, R_OK) != 0) {
        perrorf("fatal: can't access apk %s\n", apk_path);
        exit(EXIT_FATAL_PM_PATH);
    }

    start_server(apk_path, SERVER_CLASS_PATH, SERVER_NAME);
}
