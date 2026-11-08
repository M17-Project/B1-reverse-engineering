/* spkmode: set the intercom speaker-amp mode on the RFinder B1-Plus, nothing else.
 * Same call the RFinder app makes: ioctl(/dev/intercom_device, 0x4906, n), n = 0 or 3 only
 * (3 = "AMP_SPEAKER", the amp fed by the radio module; 0 = the other value the app uses).
 * The command and the allowed values are hard-coded on purpose.
 * usage: spkmode 0|3
 */
#include <fcntl.h>
#include <stdio.h>
#include <sys/ioctl.h>
#include <unistd.h>

#define INTERCOM_SPK_MODE 0x4906

int main(int argc, char **argv)
{
    if (argc != 2 || (argv[1][0] != '0' && argv[1][0] != '3') || argv[1][1]) {
        fprintf(stderr, "usage: %s 0|3\n", argv[0]);
        return 2;
    }
    unsigned long n = (unsigned long)(argv[1][0] - '0');
    int fd = open("/dev/intercom_device", O_RDONLY);
    if (fd < 0) { perror("open /dev/intercom_device"); return 1; }
    int r = ioctl(fd, INTERCOM_SPK_MODE, n);
    printf("ioctl(0x%x, %lu) = %d\n", INTERCOM_SPK_MODE, n, r);
    if (r < 0) perror("ioctl");
    close(fd);
    return r < 0;
}
