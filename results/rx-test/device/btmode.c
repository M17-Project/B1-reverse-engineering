/* btmode: set Intercom BT mode on the RFinder B1-Plus, nothing else.
 * Same call as libintercomjni setBTMode(n): ioctl(/dev/intercom_device, 0x4905, n).
 * The command is hard-coded on purpose: this tool cannot issue any other ioctl (e.g. PTT 0x4902).
 * usage: btmode 0|1
 */
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/ioctl.h>
#include <unistd.h>

#define INTERCOM_BT_MODE 0x4905

int main(int argc, char **argv)
{
    if (argc != 2 || (argv[1][0] != '0' && argv[1][0] != '1') || argv[1][1]) {
        fprintf(stderr, "usage: %s 0|1\n", argv[0]);
        return 2;
    }
    unsigned long n = (unsigned long)(argv[1][0] - '0');
    int fd = open("/dev/intercom_device", O_RDONLY);
    if (fd < 0) { perror("open /dev/intercom_device"); return 1; }
    int r = ioctl(fd, INTERCOM_BT_MODE, n);
    printf("ioctl(0x%x, %lu) = %d\n", INTERCOM_BT_MODE, n, r);
    if (r < 0) perror("ioctl");
    close(fd);
    return r < 0;
}
