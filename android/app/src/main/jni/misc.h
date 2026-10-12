#ifndef SEFIRAH_MISC_H
#define SEFIRAH_MISC_H

#include <sys/types.h>

typedef void (*foreach_proc_function)(pid_t pid);

int get_proc_name(int pid, char *name, size_t size);
void foreach_proc(foreach_proc_function func);

#endif
/**/