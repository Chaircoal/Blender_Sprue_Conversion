# 🔌 **Blender_Sprue_Conversion** Blender Add-on
Blender add-on to segment STL files of miniature models and automatically generate a sprue sheet for injection molding.
## 🔑 Key Features
- Interactive Mesh Segmentation
- Design for Manufacturing checks
- Automatic gate placement
- Vertex priority heatmapping (for gate placement)
- Automatic sprue generation
- Automatic piece orientation

## 📦 Installation Instructions
1. Download the zip. Do not extract it.
2. In Blender, EDIT -> Preferences -> Add-ons -> (Top right dropdown -> Install From Disk) -> select ‘sprue_converter_addon.zip'
3. Check ON if not already (Checkbox should be marked)
4. Hotkey 'N' to open the sidebar.
5. 'Sprue Tool' will now appear as a tab in your sidebar.

## ℹ️ How to Use
1. Create a new scene in Blender
2. Import the .stl file of a model you wish to work with
3. Do an initial preprocessing of the mesh
4. Segment mesh using our toolkit
5. (Optional) Paint on priority heatmap for desired gate placement
6. Tweak settings to your desire
7. Generate a print-ready sprue sheet

### ✂️ Mesh Segmentation
1. Click ‘Select Part to Extract’. Select vertices of the part you want separated.
2. Click ‘Generate Slices’. There are also advanced settings you can adjust.
3. If the boundary is jagged, use the ‘Relax Boundary’ to smoothen it.
4. Repeat steps 1-3 until you’re satisfied with the cut.
5. Click ‘Slice Mesh’ to separate the segments.

### 🌡️ Priority Heatmap Weight Painting (optional - recommended for optimal results)
1. Select a segment of your model
2. Click on “paint gate priority” button
3. A brush tool using Blender’s built in “Weight Paint” feature will appear.
4. Brush priority onto areas you would like to prioritize during automatic gate placement.
5. Repeat for other segments (press the “clear gate priority” button if you make mistakes)
6. Once satisfied you are ready to move on and generate your sprue sheet.

### 🔨 Build Sprue Frame
1. Change settings to desired levels
2. If parts are hidden within the tree they will not be included in the sprue. Ensure they are not if you do not want this.
3. Click the “Build Sprue Layout” button.

## 🎞️ Check out our cool youtube tutorial!
*Link placeholder*
