# SAM 2.1 Tiny: local image segmentation

Copy the example into a paper workspace and run `python build_scene.py` there.
Install the official SAM 2 package and supply its **SAM 2.1 tiny** checkpoint
locally as `sam2.1_hiera_tiny.pt`. Runtime only reads local weights. This is a
synthetic wiring image, not a segmentation benchmark.

The selected tier changes the task: point-guided mask (25), point/box-guided
candidate masks (75), or automatic mask proposals over the whole image (100).
PNG masks stay in the local run artifacts; their text summaries can accompany
the platform's existing research record. Predicted IoU is not measured IoU.

Official project and checkpoint instructions:
<https://github.com/facebookresearch/sam2>

The combined CPU examples were tested with upstream source revision
`2b90b9f5ceec907a1c18123530e92e794ad901a4` and CUDA-extension building disabled
(`SAM2_BUILD_CUDA=0`). The supplied Tiny checkpoint had SHA256
`7402e0d864fa82708a20fbd15bc84245c2f26dff0eb43a4b5b93452deb34be69`.
Neither the source package nor the weights are bundled in this extension.
