from linkml_model import SchemaDefinition

from sheet2linkml.model import ModelElement
from pygsheets import worksheet
from linkml_model.meta import ClassDefinition, SlotDefinition
import logging
import re

class Entity(ModelElement):
    """
    An entity represents a class of data that we need to model.

    It is represented by a single worksheet in a Google Sheet spreadsheet.
    """

    def __init__(self, model, sheet: worksheet, name: str, rows: list[dict[str, str]]):
        """
        Create an entity based on a GSheetModel and a Google Sheet worksheet.

        :param model: The GSheetModel that this entity is a part of.
        :param sheet: A Google Sheet worksheet describing this entity.
        :param name: The name of this entity.
        :param rows: The rows in the spreadsheet describing this entity (as dictionaries of str -> str).
        """

        self.model = model
        self.worksheet = sheet
        self.entity_name = name
        self.rows = rows

    @property
    def attribute_rows(self) -> list[dict[str, str]]:
        """
        Returns this entity as a list of attribute rows.

        An attribute row is one where the COL_ATTRIBUTE_NAME row is not empty.

        :return: A list of named rows in this sheet.
        """
        return [
            row for row in self.rows if row.get(EntityWorksheet.COL_ATTRIBUTE_NAME) is not None
        ]

    @property
    def attributes(self):
        """
        Returns a list of attributes in this entity. We construct this by wrapping the
        attribute rows with Attribute().

        :return: A list of all the attributes in this entity.
        """

        return [Attribute(self.model, self, dct) for dct in self.attribute_rows]

    @property
    def entity_row(self) -> dict[str, str]:
        """
        Returns the "entity row" -- the single row in the spreadsheet that represents this
        entity itself. Writes errors in the logs if more than one "entity row" is found (only the
        first will be used).

        :return: A dictionary representing a row in the spreadsheet that represents this entity.
        """

        # Find all entity rows
        entity_rows = [
            row for row in self.rows if row.get(EntityWorksheet.COL_ATTRIBUTE_NAME) is None
        ]

        # Report an error if no rows were found.
        if not entity_rows:
            # raise RuntimeError(f'Entity does not have an entity row: {self}')
            logging.error(f"Entity contains no entity row: {self}")
            return dict()

        # Report an error if more than one row was found.
        if len(entity_rows) > 1:
            logging.error(
                f'Entity contains more than one "entity row", only the first one will be used: {self}'
            )
            for row in entity_rows:
                logging.error(f" - Found entity row: {row}")

        return entity_rows[0]

    def __str__(self):
        """
        :return: A text description of this entity.
        """

        return f'{self.__class__.__name__} named {self.name} from worksheet "{self.worksheet.title}" containing {len(self.attribute_rows)} attributes'

    @property
    def name(self) -> str:
        """
        :return: A name for this entity.
        """
        return (self.entity_name or '(unnamed entity)').strip()

    def get_filename(self) -> str:
        """
        Return this entity as a filename, which we calculate by making the entity name safe for file systems.

        :return: A filename that can be used for this entity.
        """

        # Taken from https://stackoverflow.com/a/46801075/27310
        name = str(self.name).strip().replace(" ", "_")
        return re.sub(r"(?u)[^-\w.]", "", name)

    def to_markdown(self) -> str:
        """
        Returns a reference to this entity in Markdown. We include the name, worksheet name and worksheet URL.

        :return: A Markdown representation of this entity.
        """

        return f"[{self.name} in sheet {self.worksheet.title}]({self.worksheet.url})"

    def as_linkml(self, root_uri) -> ClassDefinition:
        """
        Returns a LinkML ClassDefinition describing this entity, including attributes.

        :param root_uri: The root URI to use for this entity.
        :return: A LinkML ClassDefinition describing this entity.
        """
        logging.info(f"Generating LinkML for {self}")

        # Basic metadata
        cls: ClassDefinition = ClassDefinition(
            name=self.name,
            description=(self.entity_row.get("Description") or '').strip(),
            # comments=self.entity_row.get("Comments"),
        )

        if self.name != 'Entity':
            cls.is_a = 'Entity'

        # Additional metadata

        # We add a 'derived from' note to the notes field, which might be
        # a string or a list, apparently.
        derived_from = f"Derived from {self.to_markdown()}"
        if isinstance(cls.notes, list):
            cls.notes.append(derived_from)
        elif isinstance(cls.notes, str):
            cls.notes = cls.notes + f"\n{derived_from}"
        else:
            cls.notes = derived_from

        # TODO: Add mappings (https://linkml.github.io/linkml-model/docs/mappings/)

        # Now generate LinkML for all of the attributes.
        cls.attributes = {attribute.name: attribute.as_linkml(root_uri) for attribute in self.attributes}

        return cls


class Attribute:
    """
    An attribute represents a single property within an entity.

    It is represented by a single row in a Google Sheet spreadsheet.
    """

    def __init__(self, model, entity, row: dict[str, str]):
        """
        Create an attribute based on a GSheetModel and a Google Sheet worksheet.

        :param model: The GSheetModel that this attribute is a part of.
        :param entity: The Entity that this attribute is a part of.
        :param row: The row describing this attribute (as a dictionary of str -> str).
        """

        self.model = model
        self.entity = entity
        self.row = row

    @property
    def name(self):
        """
        :return: A name for this attribute.
        """
        return (
            self.row.get(EntityWorksheet.COL_ATTRIBUTE_NAME)
            or self.row.get("Name")
            or self.row.get("name")
        )

    def __str__(self):
        """
        :return: A text description of this row.
        """

        return f'{self.__class__.__name__} named "{self.name}" containing {len(self.row)} properties'

    def counts(self) -> (int, int):
        """
        Returns the minimum and maximum cardinality, determined by parsing the Cardinality column.
        If the string is `?..m`, this indicates that there is no maximum cardinality -- which we
        report by returning None instead of the maximum cardinality.

        :return: The minimum and maximum cardinality by reading the 'Cardinality' column.
        """

        # A default cardinality to return if none can be parsed.
        default = 0, None

        cardinality = self.row.get(EntityWorksheet.COL_CARDINALITY)
        if not cardinality:
            return default

        # We currently use `1..m` to indicate that there is no maximum cardinality.
        # We might eventually need to support `1..*` as well.
        m = re.compile("^(\\d+)\\.\\.(\\d+|m)$").match(str(cardinality))
        if not m:
            return default

        min_count = int(m.group(1))
        max_count = None
        if (
            m.group(2) != "m"
        ):  # We use '..m' to indicate that there is no maximum value.
            max_count = int(m.group(2))

        return min_count, max_count

    def as_linkml(self, root_uri) -> SlotDefinition:
        """
        Returns this attribute as a LinkML SlotDefinition.

        :param root_uri: The root URI to use for this SlotDefinition.
        :return: A LinkML SlotDefinition representing this attribute.
        """

        data = self.row
        min_count, max_count = self.counts()

        # Calculate the range.
        attribute_range = "string"    # Default to linkml:string.
        if EntityWorksheet.COL_TYPE in data:
            attribute_range = data.get(EntityWorksheet.COL_TYPE) or "string"

            # For primitive types, we need to add `ccdh_` to the start of the type name.
            if attribute_range[0].islower():
                attribute_range = f'ccdh_{attribute_range}'

        slot: SlotDefinition = SlotDefinition(
            name=data.get(EntityWorksheet.COL_ATTRIBUTE_NAME) or "",
            description=(data.get("Description") or '').strip(),
            # comments=data.get("Comments"),
            # notes=data.get("Developer Notes"),
            required=(min_count > 0),
            multivalued=(max_count is None or max_count > 1),
            range=attribute_range
        )

        cardinality = data.get(EntityWorksheet.COL_CARDINALITY)
        if cardinality:
            slot.notes.append(f"Cardinality: {cardinality}")

        return slot


class EntityWorksheet(ModelElement):
    """
    A Worksheet represents a single worksheet in a GSheetModel. A single sheet usually contains
    information on a single Entity, but sometimes multiple entities may be described in a single
    Worksheet. In that case, this Worksheet will return multiple entities.
    """

    # Some column names.
    COL_STATUS = "Status"
    COL_ENTITY_NAME = "Entity"
    COL_ATTRIBUTE_NAME = "Attribute"
    COL_CARDINALITY = "Cardinality"
    COL_TYPE = "Type"

    @staticmethod
    def is_sheet_entity(worksheet: worksheet):
        """Identify worksheets containing entities, i.e. those that have:
            - COL_STATUS in cell A1, and
            - COL_ENTITY_NAME in cell B1, and
            - COL_ATTRIBUTE_NAME in cell C1.
        """
        return worksheet.get_values("A1", "C1") == [[EntityWorksheet.COL_STATUS, EntityWorksheet.COL_ENTITY_NAME, EntityWorksheet.COL_ATTRIBUTE_NAME]]

    def __init__(self, model, sheet: worksheet):
        """
        Create a worksheet based on a GSheetModel and a Google Sheet worksheet.

        :param model: The GSheetModel that this worksheet is a part of.
        :param sheet: A Google Sheet worksheet describing this worksheet.
        """

        self.model = model
        self.worksheet = sheet

    @property
    def rows(self) -> list[dict]:
        """
        Returns this entity as a list of rows. We use the header row to create these dictionaries.

        :return: A list of the rows in this sheet.
        """
        return self.worksheet.get_all_records(empty_value=None)

    @property
    def included_rows(self) -> list[dict]:
        """
        Returns this entity as a list of included rows.

        An included row is one whose COL_STATUS is set to 'include'.

        :return: A list of included rows in this sheet.
        """
        return [
            row for row in self.rows if row.get(EntityWorksheet.COL_STATUS, "") == "include"
        ]

    @property
    def entity_names(self) -> list[str]:
        """
        Return a list of all the entity names in this worksheet.

        :return: A list of all the entity names in this worksheet.
        """

        return [(row.get(EntityWorksheet.COL_ENTITY_NAME) or "") for row in self.included_rows()]

    @property
    def entities_as_included_rows(self) -> dict[str, list[dict]]:
        """
        Group the list of rows based on having identical COL_ENTITY_NAME values.

        :return: A dict with keys of COL_ENTITY_NAME values and values of included rows having that value.
        """

        result = dict()

        for row in self.included_rows:
            entity_name = row.get(EntityWorksheet.COL_ENTITY_NAME) or ""
            if not (entity_name in result):
                result[entity_name] = list()

            result[entity_name].append(row)

        # The Google Sheet might indicate that the entity row (the row without an attribute name) should be excluded.
        # If any other rows have been included for this entity, however, they would be used to define the entity,
        # even though the intention was to exclude that entity. In order to prevent this, we will check for any included
        # rows that don't have an entity row -- such groups will be filtered out here.
        filtered = dict()

        for name, rows in result.items():
            if any(row.get(EntityWorksheet.COL_ATTRIBUTE_NAME) is None for row in rows):
                filtered[name] = rows
            else:
                logging.warning(f'- Ignoring entity {name} in worksheet {self.name} as it does not have an entity row.')

        return filtered

    @property
    def grouped_entities(self) -> dict[str, Entity]:
        """
        Return a list of entities in this file, grouped into a dict by key name.

        :return: A dict with keys of COL_ENTITY_NAME values and values of Entity objects.
        """

        return {
            k: Entity(self.model, self.worksheet, k, v)
            for k, v in self.entities_as_included_rows.items()
        }

    @property
    def entities(self) -> list[Entity]:
        """
        Return a list of entities in this file.

        :return: A list of Entity objects.
        """

        return list(self.grouped_entities.values())

    @property
    def name(self) -> str:
        """
        :return: A name for this worksheet.
        """
        return self.worksheet.title

    def get_filename(self) -> str:
        """
        Return this worksheet as a filename, which we calculate by making the entity name safe.

        :return: A filename that could be used for this entity.
        """

        # Taken from https://stackoverflow.com/a/46801075/27310
        name = str(self.worksheet.title).strip().replace(" ", "_")
        return re.sub(r"(?u)[^-\w.]", "", name)

    def to_markdown(self) -> str:
        """
        :return: A Markdown representation of this entity.
        """

        return f"[{self.worksheet.title}]({self.worksheet.url})"

    def as_linkml(self, root_uri) -> list[SchemaDefinition]:
        """
        Return all LinkML SchemaDefinitions in this worksheet. We do this by converting each
        Entity into its LinkML SchemaDefinition.

        :param root_uri: The root URI to use for this worksheet.
        :return: A list of LinkML SchemaDefinitions representing entities in this worksheet.
        """
        return [entity.as_linkml(root_uri) for entity in self.entities.values()]