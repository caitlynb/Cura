from UM.Logger import Logger

from PyQt5.QtCore import Qt, pyqtSlot, QObject
from PyQt5.QtWidgets import QApplication

from cura.ObjectsModel import ObjectsModel
from cura.BuildPlateModel import BuildPlateModel
from cura.Scene.CuraSceneNode import CuraSceneNode
from cura.Settings.ExtruderManager import ExtruderManager

from UM.Application import Application
from UM.Scene.Iterator.DepthFirstIterator import DepthFirstIterator
from UM.Scene.SceneNode import SceneNode
from UM.Scene.Selection import Selection
from UM.Signal import Signal


class CuraSceneController(QObject):
    activeBuildPlateChanged = Signal()

    def __init__(self, objects_model: ObjectsModel, build_plate_model: BuildPlateModel):
        super().__init__()

        self._objects_model = objects_model
        self._build_plate_model = build_plate_model
        self._active_build_plate = -1

        self._last_selected_index = 0
        self._max_build_plate = 1  # default

        Application.getInstance().getController().getScene().sceneChanged.connect(self.updateMaxBuildPlate)  # it may be a bit inefficient when changing a lot simultaneously
        Application.getInstance().getController().toolOperationStopped.connect(self._onToolOperationStopped)

    def updateMaxBuildPlate(self, *args):
        if args:
            source = args[0]
        else:
            source = None
        if not isinstance(source, SceneNode):
            return
        max_build_plate = self._calcMaxBuildPlate()
        changed = False
        if max_build_plate != self._max_build_plate:
            self._max_build_plate = max_build_plate
            changed = True
        if changed:
            self._build_plate_model.setMaxBuildPlate(self._max_build_plate)
            build_plates = [{"name": "Build Plate %d" % (i + 1), "buildPlateNumber": i} for i in range(self._max_build_plate + 1)]
            self._build_plate_model.setItems(build_plates)
            if self._active_build_plate > self._max_build_plate:
                build_plate_number = 0
                if self._last_selected_index >= 0:  # go to the buildplate of the item you last selected
                    item = self._objects_model.getItem(self._last_selected_index)
                    if "node" in item:
                        node = item["node"]
                        build_plate_number = node.callDecoration("getBuildPlateNumber")
                self.setActiveBuildPlate(build_plate_number)
            # self.buildPlateItemsChanged.emit()  # TODO: necessary after setItems?

    def _calcMaxBuildPlate(self):
        max_build_plate = 0
        for node in DepthFirstIterator(Application.getInstance().getController().getScene().getRoot()):
            if node.callDecoration("isSliceable"):
                build_plate_number = node.callDecoration("getBuildPlateNumber")
                max_build_plate = max(build_plate_number, max_build_plate)
        return max_build_plate

    ##  Either select or deselect an item
    @pyqtSlot(int)
    def changeSelection(self, index):
        modifiers = QApplication.keyboardModifiers()
        ctrl_is_active = modifiers & Qt.ControlModifier
        shift_is_active = modifiers & Qt.ShiftModifier

        if ctrl_is_active:
            item = self._objects_model.getItem(index)
            node = item["node"]
            if Selection.isSelected(node):
                Selection.remove(node)
            else:
                Selection.add(node)
        elif shift_is_active:
            polarity = 1 if index + 1 > self._last_selected_index else -1
            for i in range(self._last_selected_index, index + polarity, polarity):
                item = self._objects_model.getItem(i)
                node = item["node"]
                Selection.add(node)
        else:
            # Single select
            item = self._objects_model.getItem(index)
            node = item["node"]
            build_plate_number = node.callDecoration("getBuildPlateNumber")
            if build_plate_number is not None and build_plate_number != -1:
                self.setActiveBuildPlate(build_plate_number)
            Selection.clear()
            Selection.add(node)

        self._last_selected_index = index

    @pyqtSlot(int)
    def setActiveBuildPlate(self, nr):
        if nr == self._active_build_plate:
            return
        Logger.log("d", "Select build plate: %s" % nr)
        self._active_build_plate = nr
        Selection.clear()

        self._build_plate_model.setActiveBuildPlate(nr)
        self._objects_model.setActiveBuildPlate(nr)
        self.activeBuildPlateChanged.emit()

    @staticmethod
    def createCuraSceneController():
        objects_model = Application.getInstance().getObjectsModel()
        build_plate_model = Application.getInstance().getBuildPlateModel()
        return CuraSceneController(objects_model = objects_model, build_plate_model = build_plate_model)

    @staticmethod
    def getSceneBoundingBox():
        max_x = Application.getInstance().getGlobalContainerStack().getProperty("machine_width", "value")
        max_y= Application.getInstance().getGlobalContainerStack().getProperty("machine_depth", "value")
        min_x = 0
        min_y = 0
        nodes = Application.getInstance().getController().getScene().getRoot().getChildren()
        nodes = list(filter(lambda node: isinstance(node, CuraSceneNode) and not node.isOutsideBuildArea(), nodes))
        if len(nodes) > 0:
            min_x = min(nodes, key=lambda node: node.getBoundingBox().minimum.x).getBoundingBox().minimum.x + max_x/2
            min_y = min(nodes, key=lambda node: node.getBoundingBox().minimum.z).getBoundingBox().minimum.z + max_y/2
            max_x = max(nodes, key=lambda node: node.getBoundingBox().maximum.x).getBoundingBox().maximum.x + max_x/2
            max_y = max(nodes, key=lambda node: node.getBoundingBox().maximum.z).getBoundingBox().maximum.z + max_y/2
        return [[max_x, max_y], [max_x, min_y], [min_x, max_y], [min_x, min_y]]

    def _onToolOperationStopped(self, tool = None):
        global_stack = Application.getInstance().getGlobalContainerStack()
        prime_tower = global_stack.getProperty("prime_tower_enable", "value")
        if prime_tower and len(ExtruderManager.getInstance().getUsedExtruderStacks()) > 1:
            global_stack.propertyChanged.emit("prime_tower_position_x", "value")
            global_stack.propertyChanged.emit("prime_tower_position_y", "value")