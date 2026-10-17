#ifndef METABROWSER_CONVERSATION_STORE_H_
#define METABROWSER_CONVERSATION_STORE_H_
#include <string>
#include <vector>
#include "base/files/file_path.h"
#include "base/values.h"
namespace metabrowser {
// UI snapshots and append-only events are separate from SDK checkpoints.
// Credentials and private account events never enter either projection.
class ConversationStore {
 public:
  static base::FilePath Root();
  static std::vector<base::DictValue> List();
  static base::DictValue Load(const std::string& id);
  static void Save(base::DictValue record);
  static void Event(const std::string& id,std::string encoded);
};
}
#endif
