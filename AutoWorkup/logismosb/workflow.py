from nipype.interfaces.utility import IdentityInterface
from nipype.pipeline import Node, Workflow
from interfaces import *
import json


def get_local_file_location(relative_file_name):
    # credit: http://stackoverflow.com/questions/7165749/open-file-in-a-relative-location-in-python
    import os
    script_dir = os.path.abspath(os.path.dirname(__file__))  # <-- absolute dir the script is in
    return os.path.join(script_dir, relative_file_name)


def read_json_config(relative_file_name):
    # HACK: read the json file in this folder
    config_file_path = get_local_file_location(relative_file_name)
    with open(config_file_path, "rb") as config_file:
        config = json.load(config_file)
    return config


def create_logb_workflow(name="LOGISMOSB_WF", master_config=None):
    logb_wf = Workflow(name=name)

    config = read_json_config("config.json")
    config['atlas_info'] = get_local_file_location(config['atlas_info'])

    inputs_node = Node(
        IdentityInterface(
            fields=['t1_file',
                    't2_file',
                    'posterior_files',
                    'joint_fusion_file',
                    'brainlabels_file',
                    'hncma_atlas']), name="inputspec")
    inputs_node.run_without_submitting = True

    white_matter_masking_node = Node(interface=WMMasking(), name="WMMasking")
    white_matter_masking_node.inputs.dilation = config['WMMasking']['dilation']
    if master_config and master_config['labelmap_colorlookup_table']:
        white_matter_masking_node.inputs.atlas_info = master_config['labelmap_colorlookup_table']
    else:
        white_matter_masking_node.inputs.atlas_info = config['atlas_info']

    logb_wf.connect([(inputs_node, white_matter_masking_node, [("posterior_files", "posterior_files"),
                                                               ("joint_fusion_file", "atlas_file"),
                                                               ("brainlabels_file", "brainlabels_file")])])

    gm_labels = Node(interface=CreateGMLabelMap(), name="GM_Labelmap")
    gm_labels.inputs.atlas_info = config['atlas_info']
    logb_wf.connect([(inputs_node, gm_labels, [('joint_fusion_file', 'atlas_file')])])

    logismosb_output_node = create_output_spec(["wmsurface_file", "gmsurface_file"], config["hemisphere_names"],
                                               name="outputspec")

    for hemisphere in config["hemisphere_names"]:
        genus_zero_filter = Node(interface=GenusZeroImageFilter(), name="{0}_GenusZeroImageFilter".format(hemisphere))
        genus_zero_filter.inputs.connectivity = config['GenusZeroImageFilter']['connectivity']
        genus_zero_filter.inputs.biggestComponent = config['GenusZeroImageFilter']['biggestComponent']
        genus_zero_filter.inputs.connectedComponent = config['GenusZeroImageFilter']['connectedComponent']
        genus_zero_filter.inputs.out_mask = "{0}_genus_zero_white_matter.nii.gz".format(hemisphere)

        logb_wf.connect([(white_matter_masking_node, genus_zero_filter, [('{0}_wm'.format(hemisphere), 'in_file')])])

        surface_generation = Node(interface=BRAINSSurfaceGeneration(),
                                  name="{0}_BRAINSSurfaceGeneration".format(hemisphere))
        surface_generation.inputs.smoothSurface = config['BRAINSSurfaceGeneration']['smoothSurface']
        surface_generation.inputs.numIterations = config['BRAINSSurfaceGeneration']['numIterations']
        surface_generation.inputs.out_file = "{0}_white_matter_surface.vtk".format(hemisphere)

        logb_wf.connect([(genus_zero_filter, surface_generation, [('out_file', 'in_file')])])

        logismosb = Node(interface=LOGISMOSB(), name="{0}_LOGISMOSB".format(hemisphere))
        logismosb.inputs.smoothnessConstraint = config['LOGISMOSB']['smoothnessConstraint']
        logismosb.inputs.nColumns = config['LOGISMOSB']['nColumns']
        logismosb.inputs.columnChoice = config['LOGISMOSB']['columnChoice']
        logismosb.inputs.columnHeight = config['LOGISMOSB']['columnHeight']
        logismosb.inputs.nodeSpacing = config['LOGISMOSB']['nodeSpacing']
        logismosb.inputs.w = config['LOGISMOSB']['w']
        logismosb.inputs.a = config['LOGISMOSB']['a']
        logismosb.inputs.nPropagate = config['LOGISMOSB']['nPropagate']
        logismosb.inputs.basename = hemisphere
        if config['LOGISMOSB']['thickRegions']:
            logismosb.inputs.thick_regions = config['LOGISMOSB']['thickRegions']
        else:
            logismosb.inputs.useHNCMALabels = True

        logb_wf.connect([(inputs_node, logismosb, [("t1_file", "t1_file"),
                                                   ("t2_file", "t2_file"),
                                                   ('hncma_atlas', 'atlas_file')]),
                         (genus_zero_filter, logismosb, [("out_file", "wm_file")]),
                         (surface_generation, logismosb, [("out_file", "mesh_file")]),
                         (white_matter_masking_node, logismosb, [('{0}_boundary'.format(hemisphere),
                                                                  'brainlabels_file')]),
                         (logismosb, logismosb_output_node, [("gmsurface_file",
                                                              "{0}_gmsurface_file".format(hemisphere)),
                                                             ("wmsurface_file",
                                                              "{0}_wmsurface_file".format(hemisphere))])])

        ctx_thickness = Node(ComputeDistance(), name="{0}_ctx_thickness".format(hemisphere))
        ctx_thickness.inputs.atlas_info = config['atlas_info']
        ctx_thickness.inputs.hemisphere = hemisphere
        logb_wf.connect([(gm_labels, ctx_thickness, [('out_file', 'labels_file')])])

    return logb_wf


def create_output_spec(outputs, hemisphere_names, name):
    final_output_names = list()
    for output in outputs:
        for hemisphere in hemisphere_names:
            final_output_names.append("{0}_".format(hemisphere) + output)
    return Node(IdentityInterface(final_output_names), name)