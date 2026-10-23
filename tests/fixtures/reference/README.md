# NYA1 PPP reference data

The compressed observation fixture is derived from the public IGS station file
`NYA100NOR_S_20230010000_01D_30S_MO.crx.gz`, downloaded from the
[BKG IGS archive](https://igs.bkg.bund.de/root_ftp/IGS/obs/2023/001/). The
source SHA-256 is `8f7e511cd46d9effc82204dc6b7c2e11675c22c2e020779dff3296eec1d21c28`.
The fixture contains its first 240 epochs after Hatanaka decompression. Its
`TIME OF LAST OBS` header was updated to the last retained epoch; observations
were not changed.

The ANTEX fixture contains the original header and the complete GPS satellite
and `ASH701073.1     SNOW` receiver antenna blocks from
[igs20.atx](https://files.igs.org/pub/station/general/igs20.atx). The source
file's SHA-256 was `0cd58d0d9ee678d5586de6c01f576e5aceb86f4a0735a168f733dfd091c0a614`.
Other antenna blocks were removed to keep the test fixture small.

The comparison position is taken from `SOLUTION/ESTIMATE`, station NYA1 A,
solution 2, epoch `23:001:43185`, in the public CODE file
[`COD0OPSFIN_20230010000_01D_01D_SOL.SNX.gz`](https://igs.bkg.bund.de/root_ftp/IGSac/products/2243/COD0OPSFIN_20230010000_01D_01D_SOL.SNX.gz),
whose SHA-256 was `ddae20350ce8e4c14b1bc3d913c4735820dece85b545fe2071e3f8a4a9fc2f9a`.
The IGS20 ECEF estimate is X `1202433.58536398`, Y `252632.426320401` and Z
`6237772.80808920` metres. This is a published network estimate, not an
independently surveyed truth. It uses the same station and analysis-center
product family as the test, so its errors can be correlated with the PPP result.

`tests.prepare_ppp_reference` downloads the matching 2023-01-01 CODE rapid
orbit, clock and bias products and IGS broadcast navigation data, then verifies
their hashes before the solver comparison.
