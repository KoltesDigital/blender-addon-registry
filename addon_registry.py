# The MIT License (MIT)
# 
# Copyright (c) 2014 Jonathan Giroux (Bloutiouf)
# 
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
# 
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
# 
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

bl_info = {
    "name": "Addon Registry",
    "author": "Jonathan Giroux (Bloutiouf)",
    "version": (0, 1, 0),
    "blender": (2, 70, 0),
    "location": "User Preferences > Addons",
    "description": "Manage addons the easy way!",
    "warning": "",
    "wiki_url": "http://wiki.blender.org/index.php/Extensions:2.6/Py/Scripts/System/Addon_Registry",
    "category": "System"
}

# Your scripts/addons/.addon_registry should have this schema in JSON
# It is not recommended to change the values below as this addon can be updated as well.
default_configuration = {
    # the downloaded database goes here, fill this if you want a preloaded database
    "addons": {},
    # order is important, so you can override addons
    "registries": [
        {
            # URL or file path
            "url": r"https://raw.githubusercontent.com/Bloutiouf/blender-addon-registry/master/addons.json",
            # link showing up when there is an error, do not define to hide the button
            "report-url": r"https://github.com/Bloutiouf/blender-addon-registry/issues/new"
        }
    ],
    # set of proxies
    "requests-proxies": None,
    # {
        # "http": "http://10.10.1.10:3128",
        # "https": "http://10.10.1.10:1080"
    # }
    # seconds waiting to establish the connection, set to None to wait forever
    "requests-timeout": 4,
}

import addon_utils
import bpy
import copy
import hashlib
import json
import os
import requests
import shutil
import subprocess
import tempfile
import zipfile
from bpy.props import *
from bpy.types import Panel, Operator, USERPREF_HT_header, WindowManager
from string import Template
from urllib.parse import urlparse

ERROR_NONE = 0
ERROR_EXTRACT_MANUALLY = 1
ERROR_FAILED_COPY = 2
ERROR_FAILED_DOWNLOAD = 3
ERROR_FAILED_REQUEST = 4
ERROR_FAILED_RETRIEVE_ADDON_LIST = 5
ERROR_HASH_MISMATCH = 6
ERROR_NO_HASH = 7
ERROR_NOT_IN_REGISTRY = 8

error_titles = [
    None,
    "Save and extract the addon manually.",
    "Failed to copy the addon.",
    "Failed to download the addon.",
    "The addon is not downloadable.",
    "Failed to retrieve the addon list.",
    "Hash mismatch;",
    "The registry record is not hashed.",
    "Addon is not in the registry."
] 

lastError = ERROR_NONE

configuration = copy.deepcopy(default_configuration)

def get_addon_dir(dir="addons_extern", create=False):
    addon_dir = os.path.join(bpy.utils.script_path_user(), dir)
    if create and not os.path.isdir(addon_dir):
        os.makedirs(addon_dir, exist_ok=True)
    return addon_dir

def install(addon_name):
    try:
        addon = configuration["addons"][addon_name]
    except:
        return ERROR_NOT_IN_REGISTRY
    
    if "sha256" in addon:
        h = hashlib.sha256()
        hash = addon["sha256"]
    else:
        return ERROR_NO_HASH
    
    if "://" in addon["url"]:
        try:
            res = requests.get(addon["url"], proxies=configuration["requests-proxies"], timeout=configuration["requests-timeout"], stream=True, verify=True)
            res.raise_for_status()
        except:
            return ERROR_FAILED_REQUEST
        
        try:
            fd, download_path = tempfile.mkstemp()
            with os.fdopen(fd, 'wb') as file:
                for chunk in res.iter_content(1024): 
                    if chunk: # filter out keep-alive new chunks
                        file.write(chunk)
                        h.update(chunk)
        except:
            os.remove(download_path)
            return ERROR_FAILED_DOWNLOAD
    
    else:
        try:
            fd, download_path = tempfile.mkstemp()
            with os.fdopen(fd, 'wb') as file:
                with open(addon["url"], 'rb') as source:
                    chunk = source.read()
                    file.write(chunk)
                    h.update(chunk)
        except:
            os.remove(download_path)
            return ERROR_FAILED_COPY
    
    if h.hexdigest() != hash:
        return ERROR_HASH_MISMATCH
    
    for mod in addon_utils.modules(refresh=False):
        if mod.__name__ == addon_name:
            path = mod.__file__
            if os.path.isfile(path):
                os.remove(path)
                addon_utils.modules(refresh=True)
            elif os.path.isdir(path):
                shutil.rmtree(path)
                addon_utils.modules(refresh=True)
            break
    
    addon_dir = get_addon_dir(create=True)
    base = os.path.join(addon_dir, addon_name)
    if addon.get("file", False):
        os.rename(download_path, base + ".py")
    elif zipfile.is_zipfile(download_path):
        with zipfile.ZipFile(download_path) as zf:
            zf.extractall(addon_dir)
    else:
        try:
            subprocess.check_call(["7z", "x", "-o" + addon_dir, "-y", download_path])
            os.remove(download_path)
        except:
            bpy.ops.addon_registry.save_archive("INVOKE_DEFAULT", download_path=download_path, filepath=os.path.join(addon_dir, os.path.basename(urlparse(addon["url"]).path)))
            return ERROR_EXTRACT_MANUALLY
    
    return ERROR_NONE

def is_newer_version(available, installed):
    common_len = min(len(available), len(installed))
    for i in range(common_len):
        if available[i] > installed[i]:
            return True
        if available[i] < installed[i]:
            return False
    return len(available) > len(installed)

def load_configuration():
    global configuration
    try:
        with open(os.path.join(get_addon_dir(dir="addons"), ".addon_registry"), 'r') as f:
            configuration = json.load(f)
    except:
        pass

def save_configuration():
    with open(os.path.join(get_addon_dir(dir="addons", create=True), ".addon_registry"), 'w') as f:
        json.dump(configuration, f)

def update_addon_database():
    global lastError
    
    if not configuration["registries"]:
        return false
    
    success = True
    addons = configuration["addons"]
    registries_addons = dict()
    
    for registry in configuration["registries"]:
        report_url = registry.get("report-url", None)
        url = registry["url"]
        
        try:
            if "://" in url:
                res = requests.get(url, proxies=configuration["requests-proxies"], timeout=configuration["requests-timeout"], verify=True)
                res.raise_for_status()
                content = res.text
            else:
                with open(url, 'r') as f:
                    content = f.read()
            
            registry_addons = json.loads(content)
            registries_addons[url] = registry_addons.keys()
            for name, addon in registry_addons.items():
                addon["registry-url"] = url
                if report_url:
                    addon["registry-report-url"] = report_url
                addons[name] = addon
        except:
            lastError = ERROR_FAILED_RETRIEVE_ADDON_LIST
            success = False
    
    for name, addon in list(addons.items()):
        url = addon.get("registry-url", None)
        if url:
            registry_addons = registries_addons[url]
            if name not in registry_addons:
                del addons[name]
    
    configuration["addons"] = addons
    save_configuration()
    return success

class AddonRegistryPanel(Panel):
    """Addon registry panel, below the regular addon panel"""
    bl_label = "Addon registry"
    bl_space_type = "USER_PREFERENCES"
    bl_region_type = "WINDOW"
    
    @classmethod
    def poll(cls, context):
        return (context.user_preferences.active_section == 'ADDONS')
    
    def draw(self, context):
        layout = self.layout
        
        if lastError != ERROR_NONE:
            box = layout.box()
            
            box.label(icon='ERROR', text=error_titles[lastError])
            
            if lastError == ERROR_EXTRACT_MANUALLY:
                box.label("The downloaded file is not recognized. It should be an archive that you need to extract manually.")
                split = box.split(0.6)
                split.label("By installing 7-Zip and adding it to your PATH, the registry recognizes more formats.")
                row = split.row()
                row.operator("wm.url_open", icon='URL', text="Download 7-Zip").url = "http://www.7-zip.org/download.html"
                row.operator("wm.url_open", icon='URL', text="Installation instructions").url = "http://www.7-zip.org/download.html"
            
            if lastError == ERROR_FAILED_COPY:
                box.label("The addon file is unreachable.")
            
            if lastError == ERROR_FAILED_DOWNLOAD:
                box.label("Something may be wrong with your Internet connection. Please try again later.")
            
            if lastError == ERROR_FAILED_REQUEST:
                box.label("The server hosting the addon may be down. Please try again later.")
                box.label("The addon may have moved to another URL. If you think this is the case, please report it using the following button, so that the maintainer will update the registry.")
            
            if lastError == ERROR_FAILED_RETRIEVE_ADDON_LIST:
                box.label("The registry server may be down. Please try again later.")
                box.label("The registry may have moved to another URL. If you think this is the case, please report it using the following button, so that the maintainer will update the registry.")
            
            if lastError == ERROR_HASH_MISMATCH:
                box.label("The downloaded addon does not match the registry record. For security reasons, it won't be installed.")
                box.label("It could mean that the addon's author has uploaded a new version with the same URL.")
                box.label("If you think this is the case, please report it using the following button, so that the maintainer will update the registry.")
            
            if lastError == ERROR_NO_HASH:
                box.label("The registry record does not contain an expected hash, therefore the addon authenticity can't be verified.")
                box.label("You may be using an unofficial registry. If this is the case, please report it to its maintainers.")
            
            split = box.split(0.9)
            split.operator("wm.url_open", icon='URL', text="If the error persists, please report an issue to the registry maintainers").url = "https://github.com/Bloutiouf/XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX/issues/new"
            split.operator("addon_registry.hide_error", icon='X')
        
        addon_dir = get_addon_dir()
        
        userpref = context.user_preferences
        wm = context.window_manager
        
        installed_addons = {}
        for mod in addon_utils.modules(refresh=False):
            installed_addons[mod.__name__] = mod
        
        enabled_addon_names = {addon.module for addon in userpref.addons}
        
        split = layout.split(percentage=0.2)
        
        col = split.column()
        
        col.operator(UpdateDatabase.bl_idname, icon='FILE_REFRESH')
        col.separator()
        
        col.prop(wm, "addon_registry_search", text="", icon='VIEWZOOM')
        
        col.label(text="Categories")
        col.prop(wm, "addon_registry_filter", expand=True)
        
        col.separator()
        col.operator(ResetConfiguration.bl_idname, icon='CANCEL')
        
        col = split.column()
        
        filter = wm.addon_registry_filter
        search = wm.addon_registry_search.lower()
        
        for name, addon in configuration["addons"].items():
            info = addon["info"]
            available_version = info["version"]
            show_expanded = addon.get("show_expanded", False)
            
            installed_addon = installed_addons.get(name, None)
            installed_version = None
            is_installed = bool(installed_addon)
            is_newer_available = False
            is_enabled = False
            if is_installed:
                installed_info = addon_utils.module_bl_info(installed_addon)
                installed_version = list(installed_info["version"])
                is_newer_available = is_newer_version(available_version, installed_version)
                is_enabled = name in enabled_addon_names
            
            if ((filter == "All") or
                (filter == "New Version Available" and is_newer_available) or
                (filter == info["category"]) or
                (filter == "Installed" and is_installed) or
                (filter == "Not Installed" and not is_installed)
                ):
                if search and search not in info["name"].lower():
                    if info["author"]:
                        if search not in info["author"].lower():
                            continue
                    else:
                        continue
                
                peers = addon.get("peers", None)
                if peers and (type(peers) is not list or len(peers) == 0):
                    peers = None
                
                warning = info.get("warning", None)
                
                col_box = col.column()
                box = col_box.box()
                colsub = box.column()
                row = colsub.row()
                
                row.operator(Expand.bl_idname, icon='TRIA_DOWN' if show_expanded else "TRIA_RIGHT", emboss=False).addon_name = name
                
                sub = row.split(0.6)
                
                text = sub.row()
                text.label(text="%s: %s" % (info["category"], info["name"]))
                if peers:
                    text.label(icon='LINK_AREA')
                if warning:
                    text.label(icon='ERROR')
                    
                buttons = sub.split(0.5)
                
                if is_installed:
                    buttons.operator("wm.addon_remove",
                        text=".".join(map(str, installed_version)),
                        icon='CANCEL').module = name
                else:
                    buttons.label("Not installed")
                    
                if is_installed and not is_newer_available:
                    buttons.label("Latest version")
                else:
                    buttons.operator(Install.bl_idname,
                        text=".".join(map(str, available_version)),
                        icon='WORLD').addon_name = name
                
                if is_installed:
                    if is_enabled:
                        row.operator("wm.addon_disable", icon='CHECKBOX_HLT', text="", emboss=False).module = name
                    else:
                        row.operator("wm.addon_enable", icon='CHECKBOX_DEHLT', text="", emboss=False).module = name
                else:
                    sub = row.row()
                    sub.active = False
                    sub.label(icon='CHECKBOX_DEHLT', text="")
                
                if show_expanded:
                    if peers:
                        colsub.row().label(icon='LINK_AREA', text="Bundled with: " + ", ".join(configuration["addons"][peer]["info"]["name"] for peer in peers))
                    if info["description"]:
                        split = colsub.row().split(percentage=0.15)
                        split.label(text="Description:")
                        split.label(text=info["description"])
                    if info["location"]:
                        split = colsub.row().split(percentage=0.15)
                        split.label(text="Location:")
                        split.label(text=info["location"])
                    if info["author"]:
                        split = colsub.row().split(percentage=0.15)
                        split.label(text="Author:")
                        split.label(text=info["author"], translate=False)
                    if info["version"]:
                        split = colsub.row().split(percentage=0.15)
                        split.label(text="Version:")
                        split.label(text=".".join(str(x) for x in info["version"]), translate=False)
                    if warning:
                        split = colsub.row().split(percentage=0.15)
                        split.label(text="Warning:")
                        split.label(text="  " + warning, icon='ERROR')
                    
                    separators = 2
                    split = colsub.row().split(percentage=0.15)
                    split.label(text="Internet:")
                    if info["wiki_url"]:
                        split.operator("wm.url_open", text="Documentation", icon='HELP').url = info["wiki_url"]
                        separators -= 1
                    split.operator("wm.url_open", text="Report a Bug", icon='URL').url = info.get(
                            "tracker_url",
                            "http://developer.blender.org/maniphest/task/create/?project=3&type=Bug")
                    split.operator("wm.url_open", text="Manual download", icon='URL').url = addon["url"]
                    if "registry-report-url" in addon:
                        split.operator("wm.url_open", text="Report to registry", icon='ERROR').url = addon["registry-report-url"]
                        separators -= 1
                    for i in range(separators):
                        split.separator()


class Expand(Operator):
    """Display more information on this addon"""
    bl_idname = "addon_registry.addon_expand"
    bl_label = ""
    
    addon_name = StringProperty(
        name="Addon name"
        )
    
    def execute(self, context):
        try:
            addon = configuration["addons"][self.addon_name]
        except:
            self.report({"ERROR"}, "Addon is not in the registry.")
            return {"CANCELLED"}
        
        addon["show_expanded"] = not addon.get("show_expanded", False)
        return {"FINISHED"}


class Install(Operator):
    """Install the latest version"""
    bl_idname = "addon_registry.install"
    bl_label = "Version"
    
    addon_name = StringProperty(
        name="Addon name"
        )
    
    def execute(self, context):
        global lastError
        
        addon_name = str(self.addon_name)
        lastError = install(addon_name)
        
        if lastError == ERROR_EXTRACT_MANUALLY:
            return {"RUNNING_MODAL"}
        
        if lastError != ERROR_NONE:
            self.report({'ERROR'}, error_titles[lastError])
            return {'CANCELLED'}
        
        addon_utils.modules(refresh=True)
        bpy.utils.refresh_script_paths()
        bpy.ops.script.reload()
        
        return {'FINISHED'}

class HideError(Operator):
    """Hide error"""
    bl_idname = "addon_registry.hide_error"
    bl_label = "Got it"
    
    def execute(self, context):
        global lastError
        lastError = ERROR_NONE
        return {"FINISHED"}


class ResetConfiguration(Operator):
    """Reset configuration to the default values"""
    bl_idname = "addon_registry.reset_configuration"
    bl_label = "Reset configuration"
    
    def execute(self, context):
        global configuration
        configuration = copy.deepcopy(default_configuration)
        save_configuration()
        return {"FINISHED"}
    
    def draw(self, context):
        self.layout.label(text="Are you sure?")
    
    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)


class SaveArchive(Operator):
    """Manually download the addon"""
    bl_idname = "addon_registry.save_archive"
    bl_label = "Save archive"

    download_path = StringProperty(
            name="Download path",
            options={"HIDDEN"}
            )

    filepath = StringProperty(
            subtype="FILE_PATH"
            )

    def execute(self, context):
        os.rename(self.download_path, self.filepath)
        return {"FINISHED"}

    def invoke(self, context, event):
        wm = context.window_manager
        wm.fileselect_add(self)
        return {"RUNNING_MODAL"}
        return context.window_manager.invoke_props_dialog(self, width=600)


class UpdateDatabase(Operator):
    """Update addon database"""
    bl_idname = "addon_registry.update_database"
    bl_label = "Update addon database"
    
    def execute(self, context):
        global lastError
        
        if not update_addon_database():
            self.report({"ERROR"}, error_titles[lastError])
            return {"CANCELLED"}
        
        lastError = ERROR_NONE
        return {"FINISHED"}


class UpdateAll(Operator):
    """Update installed addons that have a newer version on the registry"""
    bl_idname = "addon_registry.update_all"
    bl_label = "Update addons from registry"
    
    def execute(self, context):
        global lastError
        
        bpy.ops.addon_registry.update_database()
        
        installed_addons = {}
        for mod in addon_utils.modules(refresh=False):
            installed_addons[mod.__name__] = mod

        for name, addon in configuration["addons"].items():
            info = addon["info"]
            available_version = info["version"]

            installed_addon = installed_addons.get(name, None)
            is_installed = bool(installed_addon)
            if is_installed:
                installed_info = addon_utils.module_bl_info(installed_addon)
                installed_version = list(installed_info["version"])
                is_newer_available = is_newer_version(available_version, installed_version)
                
                if is_newer_available:
                    lastError = install(name)
                    
                    if lastError == ERROR_EXTRACT_MANUALLY:
                        return {"RUNNING_MODAL"}
                    
                    if lastError != ERROR_NONE:
                        self.report({'ERROR'}, error_titles[lastError])
                        return {'CANCELLED'}
                    
        addon_utils.modules(refresh=True)
        bpy.utils.refresh_script_paths()
        bpy.ops.script.reload()
        
        return {"FINISHED"}


def update_from_registry(self, context):
    if context.user_preferences.active_section == "ADDONS":
        self.layout.operator(UpdateAll.bl_idname, icon='FILE_REFRESH')

def register():
    def addon_filter_items(self, context):
        import addon_utils

        items = [
            ("All", "All", "All Addons"),
            ("New Version Available", "New Version Available", "All New Version Available Addons"),
            ("Installed", "Installed", "All Installed Addons"),
            ("Not Installed", "Not Installed", "All Not Installed Addons")
        ]

        items_unique = set()

        for mod in addon_utils.modules(refresh=False):
            info = addon_utils.module_bl_info(mod)
            items_unique.add(info["category"])

        items.extend([(cat, cat, "") for cat in sorted(items_unique)])
        return items

    bpy.utils.register_module(__name__)
    USERPREF_HT_header.append(update_from_registry)
    
    WindowManager.addon_registry_search = StringProperty(
            name="Search",
            description="Search within the selected filter",
            )
    
    WindowManager.addon_registry_filter = EnumProperty(
        name="Category",
        description="Filter addons by category",
        items=addon_filter_items
        )
    
    load_configuration()
    update_addon_database()

def unregister():
    USERPREF_HT_header.remove(update_from_registry)
    bpy.utils.unregister_module(__name__)
    del WindowManager.addon_registry_search
    del WindowManager.addon_registry_filter

if __name__ == "__main__":
    register()