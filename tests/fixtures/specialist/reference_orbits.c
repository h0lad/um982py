#include <stdio.h>
#include "rtklib.h"

int main(void)
{
    int week;
    double toe, toc, dt;
    eph_t ephemeris = {0};
    while (scanf("%d %lf %lf %lf %lf %lf %lf %lf %lf %lf %lf %lf %lf %lf %lf %lf %lf %lf %lf %lf %lf %lf",
                 &week, &toe, &toc, &ephemeris.A, &ephemeris.e,
                 &ephemeris.M0, &ephemeris.omg, &ephemeris.i0,
                 &ephemeris.OMG0, &ephemeris.deln, &ephemeris.idot,
                 &ephemeris.OMGd, &ephemeris.cuc, &ephemeris.cus,
                 &ephemeris.crc, &ephemeris.crs, &ephemeris.cic,
                 &ephemeris.cis, &ephemeris.f0, &ephemeris.f1,
                 &ephemeris.f2, &dt) == 22) {
        double position[3], before[3], after[3], clock, cb, ca, variance;
        ephemeris.sat = satno(SYS_GPS, 1);
        ephemeris.toes = toe;
        ephemeris.toe = gpst2time(week, toe);
        ephemeris.toc = gpst2time(week, toc);
        gtime_t time = timeadd(ephemeris.toe, dt);
        eph2pos(time, &ephemeris, position, &clock, &variance);
        eph2pos(timeadd(time, -0.05), &ephemeris, before, &cb, &variance);
        eph2pos(timeadd(time, 0.05), &ephemeris, after, &ca, &variance);
        printf("%.12f %.12f %.12f %.16g %.12f %.12f %.12f %.16g\n",
               position[0], position[1], position[2], clock,
               (after[0] - before[0]) / 0.1,
               (after[1] - before[1]) / 0.1,
               (after[2] - before[2]) / 0.1,
               (ca - cb) / 0.1);
    }
    return 0;
}
