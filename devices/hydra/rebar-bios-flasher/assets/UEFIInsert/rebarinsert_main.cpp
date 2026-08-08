/* Minimal ReBarDxe inserter built on UEFITool 0.28 old_engine. */

#include <QCoreApplication>
#include <QFile>
#include <QList>
#include <QPersistentModelIndex>
#include <iostream>

#include "../basetypes.h"
#include "../ffs.h"
#include "../ffsengine.h"
#include "../treemodel.h"
#include "../types.h"

static const QByteArray PCI_BUS_GUID =
    QByteArray::fromHex("9fe31d3c07d28a40aacc731cfb7f1dd7");

static void findVolumes(TreeModel* model, const QModelIndex& index,
                        const QByteArray& guid,
                        QList<QPersistentModelIndex>& volumes)
{
    if (!index.isValid()) {
        for (int i = 0; i < model->rowCount(); ++i)
            findVolumes(model, model->index(i, 0), guid, volumes);
        return;
    }

    if (model->type(index) == Types::File &&
        model->header(index).left(sizeof(EFI_GUID)) == guid) {
        QModelIndex volume = model->findParentOfType(index, Types::Volume);
        QPersistentModelIndex persistent(volume);
        if (volume.isValid() && !volumes.contains(persistent))
            volumes.append(persistent);
    }

    for (int i = 0; i < model->rowCount(index); ++i)
        findVolumes(model, index.child(i, 0), guid, volumes);
}

static bool containsFile(TreeModel* model, const QModelIndex& volume,
                         const QByteArray& guid)
{
    for (int i = 0; i < model->rowCount(volume); ++i) {
        QModelIndex child = volume.child(i, 0);
        if (model->type(child) == Types::File &&
            model->header(child).left(sizeof(EFI_GUID)) == guid)
            return true;
    }
    return false;
}

static QModelIndex lastNonPadFile(TreeModel* model, const QModelIndex& volume)
{
    QModelIndex last;
    for (int i = 0; i < model->rowCount(volume); ++i) {
        QModelIndex child = volume.child(i, 0);
        if (model->type(child) == Types::File &&
            model->subtype(child) != EFI_FV_FILETYPE_PAD)
            last = child;
    }
    return last;
}

static QByteArray readFile(const QString& path)
{
    QFile file(path);
    if (!file.open(QFile::ReadOnly))
        return QByteArray();
    return file.readAll();
}

int main(int argc, char* argv[])
{
    QCoreApplication app(argc, argv);
    if (argc != 4) {
        std::cerr << "Usage: ReBarInsert <input-bios> <ReBarDxe.ffs> <output-bios>\n";
        return 2;
    }

    const QString inputPath = QString::fromLocal8Bit(argv[1]);
    const QString modulePath = QString::fromLocal8Bit(argv[2]);
    const QString outputPath = QString::fromLocal8Bit(argv[3]);
    const QByteArray input = readFile(inputPath);
    const QByteArray module = readFile(modulePath);
    if (input.isEmpty()) {
        std::cerr << "Cannot read input BIOS\n";
        return 1;
    }
    if (module.size() < static_cast<int>(sizeof(EFI_FFS_FILE_HEADER))) {
        std::cerr << "Cannot read a valid ReBarDxe FFS\n";
        return 1;
    }
    const QByteArray rebarGuid = module.left(sizeof(EFI_GUID));

    FfsEngine engine;
    UINT8 status = engine.parseImageFile(input);
    if (status != ERR_SUCCESS) {
        std::cerr << "UEFITool parse failed: " << errorMessage(status).toStdString() << "\n";
        return 1;
    }

    TreeModel* model = engine.treeModel();
    QList<QPersistentModelIndex> volumes;
    findVolumes(model, QModelIndex(), PCI_BUS_GUID, volumes);
    if (volumes.isEmpty()) {
        std::cerr << "No PciBus-containing firmware volume found\n";
        return 1;
    }

    std::cout << "Found " << volumes.size() << " PciBus DXE volume(s)\n";

    for (int i = 0; i < volumes.size(); ++i) {
        QModelIndex volume = volumes.at(i);
        if (!volume.isValid()) {
            std::cerr << "Target volume became invalid during edit\n";
            return 1;
        }
        if (containsFile(model, volume, rebarGuid)) {
            std::cerr << "ReBarDxe is already present in target volume " << i + 1 << "\n";
            return 1;
        }

        QModelIndex last = lastNonPadFile(model, volume);
        if (!last.isValid()) {
            std::cerr << "No insertable FFS file in target volume " << i + 1 << "\n";
            return 1;
        }

        status = engine.insert(last, module, CREATE_MODE_AFTER);
        if (status != ERR_SUCCESS) {
            std::cerr << "Insertion failed in volume " << i + 1 << ": "
                      << errorMessage(status).toStdString() << "\n";
            return 1;
        }
    }

    QByteArray output;
    status = engine.reconstructImageFile(output);
    if (status != ERR_SUCCESS) {
        std::cerr << "UEFITool reconstruction failed: "
                  << errorMessage(status).toStdString() << "\n";
        return 1;
    }

    // Reparse the bytes we will actually write and verify every PciBus volume.
    FfsEngine verify;
    status = verify.parseImageFile(output);
    if (status != ERR_SUCCESS) {
        std::cerr << "Reconstructed BIOS cannot be reparsed: "
                  << errorMessage(status).toStdString() << "\n";
        return 1;
    }

    QList<QPersistentModelIndex> verified;
    findVolumes(verify.treeModel(), QModelIndex(), PCI_BUS_GUID, verified);
    if (verified.size() != volumes.size()) {
        std::cerr << "PciBus volume count changed after reconstruction\n";
        return 1;
    }
    for (const QPersistentModelIndex& volume : verified) {
        if (!containsFile(verify.treeModel(), volume, rebarGuid)) {
            std::cerr << "ReBarDxe did not survive reconstruction\n";
            return 1;
        }
    }

    QFile file(outputPath);
    if (!file.open(QFile::WriteOnly | QFile::Truncate) ||
        file.write(output) != output.size()) {
        std::cerr << "Cannot write output BIOS\n";
        return 1;
    }

    std::cout << "Inserted and verified ReBarDxe in " << verified.size()
              << " volume(s)\n";
    std::cout << "Input size: " << input.size() << "; output size: "
              << output.size() << " bytes\n";
    return 0;
}
