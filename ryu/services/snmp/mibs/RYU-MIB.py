# PySNMP SMI module. Autogenerated from smidump -f python RYU-MIB
# by libsmi2pysnmp-0.1.3 at Sat May 18 13:27:33 2013,
# Python version sys.version_info(major=2, minor=7, micro=3, releaselevel='final', serial=0)

# Imports

( Integer, ObjectIdentifier, OctetString, ) = mibBuilder.importSymbols("ASN1", "Integer", "ObjectIdentifier", "OctetString")
( NamedValues, ) = mibBuilder.importSymbols("ASN1-ENUMERATION", "NamedValues")
( ConstraintsIntersection, ConstraintsUnion, SingleValueConstraint, ValueRangeConstraint, ValueSizeConstraint, ) = mibBuilder.importSymbols("ASN1-REFINEMENT", "ConstraintsIntersection", "ConstraintsUnion", "SingleValueConstraint", "ValueRangeConstraint", "ValueSizeConstraint")
( Bits, Integer32, ModuleIdentity, MibIdentifier, NotificationType, MibScalar, MibTable, MibTableRow, MibTableColumn, TimeTicks, Unsigned32, enterprises, ) = mibBuilder.importSymbols("SNMPv2-SMI", "Bits", "Integer32", "ModuleIdentity", "MibIdentifier", "NotificationType", "MibScalar", "MibTable", "MibTableRow", "MibTableColumn", "TimeTicks", "Unsigned32", "enterprises")
( RowStatus, TextualConvention, ) = mibBuilder.importSymbols("SNMPv2-TC", "RowStatus", "TextualConvention")

# Types

class DatapathID(TextualConvention, OctetString):
    displayHint = "1x"
    subtypeSpec = OctetString.subtypeSpec+ValueSizeConstraint(8,8)
    fixedLength = 8
    

# Objects

ryuMIB = ModuleIdentity((1, 3, 6, 1, 4, 1, 41786)).setRevisions(("2013-05-17 00:00",))
if mibBuilder.loadTexts: ryuMIB.setOrganization("Ryu project")
if mibBuilder.loadTexts: ryuMIB.setContactInfo("TODO")
if mibBuilder.loadTexts: ryuMIB.setDescription("The MIB module for Ryu project\nTODO")
ryuNotifications = MibIdentifier((1, 3, 6, 1, 4, 1, 41786, 1))
openflowNotifications = MibIdentifier((1, 3, 6, 1, 4, 1, 41786, 1, 0))
openFlow = MibIdentifier((1, 3, 6, 1, 4, 1, 41786, 2))
datapathTable = MibTable((1, 3, 6, 1, 4, 1, 41786, 2, 1))
if mibBuilder.loadTexts: datapathTable.setDescription("TODO")
datapathEntry = MibTableRow((1, 3, 6, 1, 4, 1, 41786, 2, 1, 1)).setIndexNames((0, "RYU-MIB", "dpIndex"))
if mibBuilder.loadTexts: datapathEntry.setDescription("datapath entry")
dpIndex = MibTableColumn((1, 3, 6, 1, 4, 1, 41786, 2, 1, 1, 1), DatapathID()).setMaxAccess("noaccess")
if mibBuilder.loadTexts: dpIndex.setDescription("TODO")
dpID = MibTableColumn((1, 3, 6, 1, 4, 1, 41786, 2, 1, 1, 2), DatapathID()).setMaxAccess("readonly")
if mibBuilder.loadTexts: dpID.setDescription("datapath id")
dpNBuffers = MibTableColumn((1, 3, 6, 1, 4, 1, 41786, 2, 1, 1, 3), Unsigned32()).setMaxAccess("readonly")
if mibBuilder.loadTexts: dpNBuffers.setDescription("nbuffers")
dpNTables = MibTableColumn((1, 3, 6, 1, 4, 1, 41786, 2, 1, 1, 4), Unsigned32().subtype(subtypeSpec=ValueRangeConstraint(0, 255))).setMaxAccess("readonly")
if mibBuilder.loadTexts: dpNTables.setDescription("n tables")
dpAuxiliaryID = MibTableColumn((1, 3, 6, 1, 4, 1, 41786, 2, 1, 1, 5), Unsigned32().subtype(subtypeSpec=ValueRangeConstraint(0, 255))).setMaxAccess("readonly")
if mibBuilder.loadTexts: dpAuxiliaryID.setDescription("auxiliary_id")
dpCapabilities = MibTableColumn((1, 3, 6, 1, 4, 1, 41786, 2, 1, 1, 6), Unsigned32()).setMaxAccess("readonly")
if mibBuilder.loadTexts: dpCapabilities.setDescription("capabilities")
dpRowStatus = MibTableColumn((1, 3, 6, 1, 4, 1, 41786, 2, 1, 1, 7), RowStatus()).setMaxAccess("readcreate")
if mibBuilder.loadTexts: dpRowStatus.setDescription("row status")

# Augmentions

# Notifications

datapathConnected = NotificationType((1, 3, 6, 1, 4, 1, 41786, 1, 0, 1)).setObjects(*(("RYU-MIB", "dpID"), ) )
if mibBuilder.loadTexts: datapathConnected.setDescription("datapath connected")
datapathDisconnected = NotificationType((1, 3, 6, 1, 4, 1, 41786, 1, 0, 2)).setObjects(*(("RYU-MIB", "dpID"), ) )
if mibBuilder.loadTexts: datapathDisconnected.setDescription("datapath disconnected")

# Exports

# Module identity
mibBuilder.exportSymbols("RYU-MIB", PYSNMP_MODULE_ID=ryuMIB)

# Types
mibBuilder.exportSymbols("RYU-MIB", DatapathID=DatapathID)

# Objects
mibBuilder.exportSymbols("RYU-MIB", ryuMIB=ryuMIB, ryuNotifications=ryuNotifications, openflowNotifications=openflowNotifications, openFlow=openFlow, datapathTable=datapathTable, datapathEntry=datapathEntry, dpIndex=dpIndex, dpID=dpID, dpNBuffers=dpNBuffers, dpNTables=dpNTables, dpAuxiliaryID=dpAuxiliaryID, dpCapabilities=dpCapabilities, dpRowStatus=dpRowStatus)

# Notifications
mibBuilder.exportSymbols("RYU-MIB", datapathConnected=datapathConnected, datapathDisconnected=datapathDisconnected)
