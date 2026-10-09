---
id: cv
name: Computer vision
version: 1
match: \b(computer vision|images?|visual|video|segmentation|object detection|detection|diffusion|generative image|3d|point clouds?|nerf|gaussian splatting|depth estimation|pose estimation|optical flow|vision[- ]language|vlms?|vit|convolutional|cnns?)\b
---

# Field skill: computer vision

This adds to the base reviewer skill; it overrides nothing in it.

## What to check that a generalist misses

- **The split is the claim.** Name the benchmark split each number is on
  (val or test, which version of COCO, ImageNet-1k or a subset). A result on
  val presented as test, or a subset chosen by the authors, is not comparable
  with the published numbers it sits beside.
- **Compared at equal cost.** Resolution, backbone, pre-training data and its
  size, training schedule and test-time augmentation must match the baselines
  or be stated. A gain that comes with a larger backbone, more pre-training
  images or multi-scale testing is a gain of those, until an ablation says
  otherwise.
- **Generative models.** FID, IS, CLIP score and the like depend on the
  sample count, the reference set, the resolution and the implementation:
  each must be stated, and the same for every row. A metric computed with a
  different library than the baselines' is not comparable. Human preference
  studies need their protocol: raters, pairs, randomisation, agreement.
- **Qualitative figures.** Are the examples chosen, and how? A cherry-picked
  grid shows a method can work, not that it does. Look for failure cases;
  their absence is a finding.
- **Data provenance and leakage.** Pre-training sets crawled from the web may
  contain the test images; a paper that pre-trains on such data and evaluates
  on public benchmarks should say what it did about overlap.
- **Video and 3D.** Frame sampling, clip length, the camera or scene split
  (unseen scenes, not unseen frames of seen scenes), and whether depth or pose
  came from ground truth or an estimator.

## Do not demand

- Results on every benchmark of the subfield; a representative one with a
  clear reason is enough for the claim the paper makes.
- Training at a scale the paper's question does not need.
- Comparison with a closed model that cannot be run, unless the claim is about
  that model.
