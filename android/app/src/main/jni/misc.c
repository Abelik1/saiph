#include "misc.h"

#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static ssize_t fdgets(char *buf, size_t size, int fd) {
    buf[0] = '\0';
    ssize_t ret;
    do {
        ret = read(fd, buf, size - 1);
    } while (ret < 0 && errno == EINTR);
    if (ret < 0)
        return -1;
    buf[ret] = '\0';
    return ret;
}

int get_proc_name(int pid, char *name, size_t size) {
    char buf[PATH_MAX];
    snprintf(buf, sizeof(buf), "/proc/%d/cmdline", pid);
    int fd = open(buf, O_RDONLY);
    if (fd == -1)
        return 1;
    fdgets(name, size, fd);
    close(fd);
    return 0;
}

static int is_num(const char *s) {
    for (size_t i = 0; s[i] != '\0'; ++i)
        if (s[i] < '0' || s[i] > '9')
            return 0;
    return 1;
}

void foreach_proc(foreach_proc_function func) {
    DIR *dir = opendir("/proc");
    if (!dir)
        return;

    struct dirent *entry;
    while ((entry = readdir(dir))) {
        if (entry->d_type != DT_DIR) continue;
        if (!is_num(entry->d_name)) continue;
        pid_t pid = atoi(entry->d_name);
        func(pid);
    }

    closedir(dir);
}
