import os
import bpy
import struct
from bpy_extras.io_utils import ImportHelper
from ..file_formats import GbrParser, Abr1Parser, Abr6Parser
from ..resources import get_cache_folder

class ImportBrushOperator(bpy.types.Operator, ImportHelper):
    """Extract textures of ABR or GBR brushes and append them to the current file"""
    bl_idname = "gpencil.nijigp_import_brush"
    bl_label = "Import Brushes"
    bl_category = 'View'
    bl_options = {'REGISTER', 'UNDO'}

    directory: bpy.props.StringProperty(subtype='DIR_PATH')
    files: bpy.props.CollectionProperty(type=bpy.types.OperatorFileListElement)
    filepath = bpy.props.StringProperty(name="File Path", subtype='FILE_PATH')
    filter_glob: bpy.props.StringProperty(
        default='*.gbr;*.abr',
        options={'HIDDEN'}
    )

    texture_usage: bpy.props.EnumProperty(
            name='Texture Usage',
            items=[('IMAGE', 'New Images', ''),
                    ('MATERIAL', 'New Materials', ''),
                    ('BRUSH', 'New Brushes', '')],
            default='BRUSH'
    )
    color_mode: bpy.props.EnumProperty(
            name='Color Mode',
            items=[('WHITE', 'White', ''),
                    ('BLACK', 'Black', ''),
                    ('GRAYSCALE', 'Grayscale', '')],
            default='WHITE'
    )
    icon_save_path: bpy.props.EnumProperty(
            name='Icon Folder',
            items=[('PROJECT', 'Folder of Blend File', ''),
                    ('BRUSH', 'Folder of Brush File', '')],
            default='BRUSH'
    )
    alpha_clip: bpy.props.BoolProperty(
            name='Alpha Clip',
            default=False,
            description='If applied, the transparency of the brush pixels will be either 0 or 1'
    )
    template_brush: bpy.props.StringProperty(
            name='Template Brush',
            description='When creating new brushes, copy attributes from the selected brush',
            default='Airbrush',
            search=lambda self, context, edit_text: [brush.name for brush in bpy.data.brushes if brush.use_paint_grease_pencil and brush.gpencil_tool=='DRAW']
    )
    uv_randomness: bpy.props.FloatProperty(
            name='UV Randomness',
            default=1, min=0, max=1,
            description='Rotate the brush texture randomly for each stroke point'
    )

    def draw(self, context):
        layout = self.layout
        row = layout.row()
        row.label(text = 'Import Brushes as: ')
        row.prop(self, "texture_usage", text="")
        row = layout.row()
        row.label(text = 'Brush Color: ')
        row.prop(self, "color_mode", text="")    
        row = layout.row()
        row.label(text = 'Alpha Clip: ')
        row.prop(self, "alpha_clip", text="")
        if self.texture_usage == "BRUSH":
            row = layout.row()
            row.label(text = 'Template Brush: ')
            row.prop(self, "template_brush", text="", icon='BRUSH_DATA')
            layout.prop(self, 'uv_randomness')
            row = layout.row()
            row.label(text = 'Save Icons to: ')
            row.prop(self, "icon_save_path", text="")

    def execute(self, context):
        import numpy as np

        # Determine the location to save icons. Create a new folder if necessary
        if self.texture_usage == 'BRUSH':
            if self.icon_save_path=='PROJECT' and len(bpy.path.abspath('//'))>0:
                icon_dir = bpy.path.abspath('//')
            else:
                icon_dir = self.directory
            icon_dir =   os.path.join(icon_dir, 'gp_brush_icons')
            if not os.path.exists(icon_dir):
                os.makedirs(icon_dir)
            
        for f in self.files:
            filename = os.path.join(self.directory, f.name)
            fd = open(filename, 'rb')

            # Determine the software that generates the brush file
            if f.name.split('.')[-1] == 'gbr':
                parser = GbrParser(fd.read())
            else:
                bytes = fd.read()
                major_version = struct.unpack_from('>H',bytes)[0]
                if major_version > 5:
                    parser = Abr6Parser(bytes)
                else:
                    parser = Abr1Parser(bytes)
            if not parser.check():
                self.report({"ERROR"}, "The file format of the brush cannot be recognized.")
                return {'FINISHED'}
            
            parser.parse()
            for i,brush_mat in enumerate(parser.brush_mats):
                if len(parser.brush_mats) == 1:
                    brush_name = f.name.split('.')[0]
                else:
                    brush_name = f.name.split('.')[0] + '_' + str(i)
                img_H, img_W = brush_mat.shape[0], brush_mat.shape[1]

                # Extract and convert an image texture
                if len(brush_mat.shape)==3:     # RGBA brush, for GBR only
                    image_mat = brush_mat.copy()
                else:
                    image_mat = brush_mat.reshape((img_H, img_W, 1)).repeat(4, axis=2)
                if self.color_mode == 'WHITE':
                    image_mat[:,:,0] = (image_mat[:,:,3] > 0) * 255
                    image_mat[:,:,1] = (image_mat[:,:,3] > 0) * 255
                    image_mat[:,:,2] = (image_mat[:,:,3] > 0) * 255
                elif self.color_mode == 'BLACK':
                    image_mat[:,:,0] = (image_mat[:,:,3] < 1) * 255
                    image_mat[:,:,1] = (image_mat[:,:,3] < 1) * 255
                    image_mat[:,:,2] = (image_mat[:,:,3] < 1) * 255
                if self.alpha_clip:
                    image_mat[:,:,3] = (image_mat[:,:,3] > 127) * 255
            
                # Convert texture to Blender data block
                img_obj = bpy.data.images.new(brush_name, img_W, img_H, alpha=True, float_buffer=False)
                img_obj.pixels = np.flipud(image_mat).ravel() / 255.0
                img_obj.pack()
                
                # Create GPencil material
                if self.texture_usage != 'IMAGE':
                    new_material = bpy.data.materials.new(brush_name)
                    bpy.data.materials.create_gpencil_data(new_material)
                    new_material.grease_pencil.show_stroke = True
                    new_material.grease_pencil.mode = 'BOX'
                    new_material.grease_pencil.stroke_style = 'TEXTURE'
                    new_material.grease_pencil.mix_stroke_factor = 1
                    new_material.grease_pencil.stroke_image = img_obj
                
                # Create GPencil draw brush
                if self.texture_usage == 'BRUSH':
                    new_brush: bpy.types.Brush = bpy.data.brushes[self.template_brush].copy()
                    new_brush.name = brush_name
                    new_brush.use_custom_icon = True
                    new_brush.gpencil_settings.material = new_material
                    if self.uv_randomness > 0:
                        new_brush.gpencil_settings.use_settings_random = True
                        new_brush.gpencil_settings.uv_random = self.uv_randomness

                    # Create an icon by scaling the brush texture down
                    icon_obj = img_obj.copy()
                    icon_obj.name = "icon_"+brush_name
                    icon_filepath = os.path.join(icon_dir, brush_name+'.png')
                    icon_obj.filepath = icon_filepath
                    icon_obj.scale(256,256)
                    icon_obj.save()
                    new_brush.icon_filepath = icon_filepath
                    bpy.data.images.remove(icon_obj)
                    
            fd.close()

        return {'FINISHED'}