import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional
try:
    from package.idml_package import IDMLPackage
    from model.story import StoryModel
except ImportError:
    from ..package.idml_package import IDMLPackage
    from .story import StoryModel


class DocumentModel:
    """
    High-level representation of an IDML document, providing structured
    access to its stories, styles, preferences, and spreads.
    """

    def __init__(self, package: IDMLPackage):
        self.package = package
        self.extract_dir = package.extract_dir
        self.stories: Dict[str, StoryModel] = {}
        self.styles_root: Optional[ET.Element] = None
        self.preferences_root: Optional[ET.Element] = None
        self.spreads: Dict[str, ET.Element] = {}

    def load(self):
        """Loads and parses all essential document components."""
        if not self.extract_dir:
            raise RuntimeError("Package is not unpacked.")

        # Load Styles
        styles_file = "Resources/Styles.xml"
        if (self.extract_dir / styles_file).exists():
            self.styles_root = self.package.read_xml(styles_file)

        # Load Preferences
        prefs_file = "Resources/Preferences.xml"
        if (self.extract_dir / prefs_file).exists():
            self.preferences_root = self.package.read_xml(prefs_file)

        # Load Stories
        stories_dir = self.extract_dir / "Stories"
        if stories_dir.exists():
            for story_file in sorted(stories_dir.glob("Story_*.xml")):
                root = self.package.read_xml(f"Stories/{story_file.name}")
                self.stories[story_file.name] = StoryModel(story_file, root)

        # Load Spreads
        spreads_dir = self.extract_dir / "Spreads"
        if spreads_dir.exists():
            for spread_file in sorted(spreads_dir.glob("Spread_*.xml")):
                root = self.package.read_xml(f"Spreads/{spread_file.name}")
                self.spreads[spread_file.name] = root

    def save(self):
        """Serializes all loaded models back to XML files in the package directory."""
        if self.styles_root is not None:
            self.package.write_xml("Resources/Styles.xml", self.styles_root)

        if self.preferences_root is not None:
            self.package.write_xml("Resources/Preferences.xml", self.preferences_root)

        for filename, story in self.stories.items():
            self.package.write_xml(f"Stories/{filename}", story.root)

        # Note: Spreads and MasterSpreads are normalized on disk by DocSetup
        pass
