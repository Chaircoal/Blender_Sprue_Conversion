# 🔌 **Blender_Sprue_Conversion** Blender Add-on
Blender add-on to segment STL files of miniature models and automatically generate a sprue sheet for injection molding.
## 🔑 Key Features
Interactive Mesh Segmentation
Design for Manufacturing checks
Automatic gate placement
Vertex priority heatmapping (for gate placement)
Automatic sprue generation
Automatic piece orientation

## 📦 Installation Instructions
Download the zip. Do not extract it.
In Blender, EDIT -> Preferences -> Add-ons -> (Top right dropdown -> Install From Disk) -> select ‘sprue_converter_addon.zip'
Check ON if not already (Checkbox should be marked)
Hotkey 'N' to open the sidebar.
'Sprue Tool' will now appear as a tab in your sidebar.

## ℹ️ How to Use
Create a new scene in Blender
Import the .stl file of a model you wish to work with
Do an initial preprocessing of the mesh
Segment mesh using our toolkit
(Optional) Paint on priority heatmap for desired gate placement
Tweak settings to your desire
Generate a print-ready sprue sheet

### ✂️ Mesh Segmentation
Click ‘Select Part to Extract’. Select vertices of the part you want separated.
Click ‘Generate Slices’. There are also advanced settings you can adjust.
If the boundary is jagged, use the ‘Relax Boundary’ to smoothen it.
Repeat steps 1-3 until you’re satisfied with the cut.
Click ‘Slice Mesh’ to separate the segments.

### 🌡️ Priority Heatmap Weight Painting (optional - recommended for optimal results)
Select a segment of your model
Click on “paint gate priority” button
A brush tool using Blender’s built in “Weight Paint” feature will appear.
Brush priority onto areas you would like to prioritize during automatic gate placement.
Repeat for other segments (press the “clear gate priority” button if you make mistakes)
Once satisfied you are ready to move on and generate your sprue sheet.

### 🔨 Build Sprue Frame
Change settings to desired levels
If parts are hidden within the tree they will not be included in the sprue. Ensure they are not if you do not want this.
Click the “Build Sprue Layout” button.

## 🎞️ Check out our cool youtube tutorial!
*Link placeholder*
